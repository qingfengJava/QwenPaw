# -*- coding: utf-8 -*-
"""Ontology 服务层（T4）：引用完整性校验 + ID 生成 + 状态迁移编排。

store 层纯 SQL；本层负责三类业务规则：

1. **引用完整性**：对象必须挂在已存在的 ``type_id`` 上；关系两端与
   知识互引的 ``object_id`` 必须是存活对象（违规抛 ``ValueError``，
   由 API 层转 400/404）；
2. **ID 生成**：``{前缀}_{uuid hex[:12]}``（与 kb 平面 doc_/rev_ 惯例
   一致），调用方不传 id 时生成；
3. **状态迁移编排**：迁移留档（``ontology_state_transitions`` 追加）
   + 对象 ``state`` 推进（update 白名单）两步——留档先行，对象更新
   失败时留档仍在（审计面优先），调用方可重放推进。

平面不可用（PG 三态非 pg/dual、或七表未建）时，全部方法返回
``None``/``False``（fail-soft）；值级违规 ``ValueError`` 透传。

@author qingfeng
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .models import (
    KbObjectLink,
    OntologyAction,
    OntologyObject,
    OntologyRelation,
    OntologyRule,
    OntologyStateTransition,
    OntologyType,
)
from .store import PgOntologyStore, get_ready_ontology_store


def _new_id(prefix: str) -> str:
    """``{prefix}_{uuid hex[:12]}``（与 kb 平面 ID 形态一致）。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def _store_or_none(
    store: Optional[PgOntologyStore],
) -> Optional[PgOntologyStore]:
    """显式注入优先；缺省走工厂（平面不可用返回 None）。"""
    if store is not None:
        return store
    return await get_ready_ontology_store()


# ---------------------------------------------------------------------------
# types（只读）
# ---------------------------------------------------------------------------


async def list_types(
    layer: str = "",
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyType]]:
    """List ontology types（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_types(layer)


async def get_type(
    type_id: str,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyType]:
    """Fetch one type；不存在与平面不可用都返回 None（只读无副作用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.get_type(type_id)


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------


async def create_object(
    payload: OntologyObject,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyObject]:
    """Create one object（type 引用完整性校验；id 缺省生成）。

    Raises:
        ValueError: ``type_id`` 不存在（400）；重复 id（409 由 API 层
            以 ``False`` 行数语义转出）。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    obj = payload
    if not obj.id:
        obj = obj.model_copy(update={"id": _new_id("obj")})
    if await ready.get_type(obj.type_id) is None:
        raise ValueError(f"unknown ontology type: {obj.type_id}")
    if not await ready.create_object(obj):
        raise ValueError(f"duplicate object id: {obj.id}")
    return obj


async def get_object(
    object_id: str,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyObject]:
    """Fetch one live object；平面不可用/不存在都返回 None。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.get_object(object_id)


async def list_objects(
    type_id: str = "",
    org_id: str = "",
    department_id: str = "",
    status: str = "",
    keyword: str = "",
    limit: int = 200,
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyObject]]:
    """List live objects（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_objects(
        type_id=type_id,
        org_id=org_id,
        department_id=department_id,
        status=status,
        keyword=keyword,
        limit=limit,
    )


async def update_object(
    object_id: str,
    fields: Dict[str, Any],
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyObject]:
    """Patch whitelisted fields，返回更新后的对象。

    Returns:
        更新后的对象；平面不可用返回 None，对象不存在/无可写内容
        返回 None（API 层先判存在性，不依赖本返回值歧义）。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    await ready.update_object(object_id, fields)
    return await ready.get_object(object_id)


async def soft_delete_object(
    object_id: str,
    store: Optional[PgOntologyStore] = None,
) -> Optional[bool]:
    """Logical-delete one object（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.soft_delete_object(object_id)


# ---------------------------------------------------------------------------
# relations
# ---------------------------------------------------------------------------


async def create_relation(
    payload: OntologyRelation,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyRelation]:
    """Create one directed relation（两端对象存在性校验）。

    Raises:
        ValueError: 端点对象不存在（400）；重复 id（409）。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    rel = payload
    if not rel.id:
        rel = rel.model_copy(update={"id": _new_id("rel")})
    if await ready.get_object(rel.from_id) is None:
        raise ValueError(f"relation endpoint not found: {rel.from_id}")
    if await ready.get_object(rel.to_id) is None:
        raise ValueError(f"relation endpoint not found: {rel.to_id}")
    if not await ready.create_relation(rel):
        raise ValueError(f"duplicate relation id: {rel.id}")
    return rel


async def list_relations(
    from_id: str = "",
    to_id: str = "",
    rel_type: str = "",
    limit: int = 200,
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyRelation]]:
    """List relations（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_relations(
        from_id=from_id,
        to_id=to_id,
        rel_type=rel_type,
        limit=limit,
    )


async def delete_relation(
    relation_id: str,
    store: Optional[PgOntologyStore] = None,
) -> Optional[bool]:
    """Remove one relation（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.delete_relation(relation_id)


# ---------------------------------------------------------------------------
# state transitions（编排：留档 + 对象 state 推进）
# ---------------------------------------------------------------------------


async def apply_transition(
    object_id: str,
    to_state: str,
    trigger_type: str = "",
    operator: str = "",
    permission: str = "",
    preconditions: Optional[Dict[str, Any]] = None,
    postconditions: Optional[Dict[str, Any]] = None,
    audit_required: bool = False,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyStateTransition]:
    """记录一次状态迁移并推进对象 ``state``。

    编排顺序：对象存在性校验 → 迁移留档（先，审计面优先）→ 对象
    ``state``/``state_detail`` 推进。留档成功而对象推进失败不回滚
    留档（记录本身即事实），调用方可重放推进。

    Raises:
        ValueError: 对象不存在（404 语义）。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    obj = await ready.get_object(object_id)
    if obj is None:
        raise ValueError(f"object not found: {object_id}")
    trn = OntologyStateTransition(
        id=_new_id("trn"),
        object_id=object_id,
        from_state=obj.state,
        to_state=to_state,
        trigger_type=trigger_type,
        preconditions=preconditions or {},
        permission=permission,
        postconditions=postconditions or {},
        audit_required=audit_required,
    )
    if not await ready.create_transition(trn):
        raise ValueError(f"duplicate transition id: {trn.id}")
    await ready.update_object(
        object_id,
        {
            "state": to_state,
            "state_detail": {"last_operator": operator},
        },
    )
    return trn


async def list_transitions(
    object_id: str,
    limit: int = 100,
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyStateTransition]]:
    """List transition records of one object（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_transitions(object_id, limit)


# ---------------------------------------------------------------------------
# rules / actions（留档 CRUD）
# ---------------------------------------------------------------------------


async def create_rule(
    payload: OntologyRule,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyRule]:
    """Create one rule record（仅建模；id 缺省生成）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    rule = payload
    if not rule.id:
        rule = rule.model_copy(update={"id": _new_id("rul")})
    if not await ready.create_rule(rule):
        raise ValueError(f"duplicate rule id: {rule.id}")
    return rule


async def list_rules(
    object_type: str = "",
    limit: int = 200,
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyRule]]:
    """List rule records（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_rules(object_type, limit)


async def create_action(
    payload: OntologyAction,
    store: Optional[PgOntologyStore] = None,
) -> Optional[OntologyAction]:
    """Create one action record（仅建模；id 缺省生成）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    action = payload
    if not action.id:
        action = action.model_copy(update={"id": _new_id("act")})
    if not await ready.create_action(action):
        raise ValueError(f"duplicate action id: {action.id}")
    return action


async def list_actions(
    object_type: str = "",
    limit: int = 200,
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[OntologyAction]]:
    """List action records（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.list_actions(object_type, limit)


# ---------------------------------------------------------------------------
# kb_object_links（知识 ↔ 本体互引）
# ---------------------------------------------------------------------------


async def create_link(
    payload: KbObjectLink,
    store: Optional[PgOntologyStore] = None,
) -> Optional[KbObjectLink]:
    """Create one link（对象存在性校验；kb 文档侧不跨模块强校验）。

    Raises:
        ValueError: 对象不存在（400）；重复 id（409）。
    """
    ready = await _store_or_none(store)
    if ready is None:
        return None
    link = payload
    if not link.id:
        link = link.model_copy(update={"id": _new_id("lnk")})
    if await ready.get_object(link.object_id) is None:
        raise ValueError(f"link target object not found: {link.object_id}")
    if not await ready.create_link(link):
        raise ValueError(f"duplicate link id: {link.id}")
    return link


async def list_links(
    document_id: str = "",
    object_id: str = "",
    store: Optional[PgOntologyStore] = None,
) -> Optional[List[KbObjectLink]]:
    """List links（文档/对象两侧视角；None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    if document_id:
        return await ready.list_links_for_document(document_id)
    if object_id:
        return await ready.list_links_for_object(object_id)
    return []


async def delete_link(
    link_id: str,
    store: Optional[PgOntologyStore] = None,
) -> Optional[bool]:
    """Remove one link（None = 平面不可用）。"""
    ready = await _store_or_none(store)
    if ready is None:
        return None
    return await ready.delete_link(link_id)


__all__ = [
    "list_types",
    "get_type",
    "create_object",
    "get_object",
    "list_objects",
    "update_object",
    "soft_delete_object",
    "create_relation",
    "list_relations",
    "delete_relation",
    "apply_transition",
    "list_transitions",
    "create_rule",
    "list_rules",
    "create_action",
    "list_actions",
    "create_link",
    "list_links",
    "delete_link",
]
