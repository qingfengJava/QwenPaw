# -*- coding: utf-8 -*-
"""Ontology 管理 API（T4）：``/api/admin/ontology`` 端点面。

权限：``PERM_ONTOLOGY_MANAGE``（``admin:ontology`` 新种子；platform_admin
经 ``PERM_ALL`` 通配天然覆盖）。全部端点 async 直调服务层——admin 面无
同步桥接需求（区别于 kb 人侧面的 def + 后台 loop 桥接）。

语义约定：

- ``503``：本体平面不可用（json 后端 / 七表未建）；
- ``404``：路径资源（对象）不存在；
- ``400``：值级违规（未知类型引用 / 关系端点不存在 / 重复 id），
  服务层 ``ValueError`` 统一转出。

@author qingfeng
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..rbac import require_perm
from ..rbac.models import PERM_ONTOLOGY_MANAGE
from ..write_audit import record_write_audit
from . import service
from .models import (
    KbObjectLink,
    OntologyAction,
    OntologyObject,
    OntologyRelation,
    OntologyRule,
    OntologyType,
)

router = APIRouter(
    prefix="/ontology",
    tags=["admin-ontology"],
    dependencies=[Depends(require_perm(PERM_ONTOLOGY_MANAGE))],
)


class TransitionBody(BaseModel):
    """状态迁移请求（对象 state 推进 + 迁移留档一次完成）。"""

    to_state: str
    trigger_type: str = ""
    operator: str = ""
    permission: str = ""
    preconditions: Dict[str, Any] = Field(default_factory=dict)
    postconditions: Dict[str, Any] = Field(default_factory=dict)
    audit_required: bool = False


def _unavailable() -> HTTPException:
    """503 异常构造（平面不可用统一出口）。"""
    return HTTPException(
        status_code=503,
        detail="ontology plane unavailable (requires pg/dual backend "
        "with alembic 0047 applied)",
    )


def _bad_request(
    exc: ValueError,
    *,
    path_resource: bool = False,
) -> HTTPException:
    """400/404 统一出口：路径资源不存在升 404，body 引用违规 400。"""
    if path_resource and "not found" in str(exc):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _object_snapshot(obj: OntologyObject) -> dict:
    """对象审计快照：仅取标识/分类/状态关键字段，避免审计行过大。"""
    return {
        "id": obj.id,
        "type_id": obj.type_id,
        "name": obj.name,
        "state": obj.state,
        "status": obj.status,
    }


def _relation_snapshot(rel: OntologyRelation) -> dict:
    """关系审计快照：标识 + 类型 + 两端。"""
    return {
        "id": rel.id,
        "type": rel.type,
        "from_id": rel.from_id,
        "to_id": rel.to_id,
    }


def _link_snapshot(link: KbObjectLink) -> dict:
    """互引审计快照：标识 + 知识侧 + 对象侧。"""
    return {
        "id": link.id,
        "kb_space_id": link.kb_space_id,
        "kb_document_id": link.kb_document_id,
        "object_id": link.object_id,
    }


# ---------------------------------------------------------------------------
# types（只读）
# ---------------------------------------------------------------------------


@router.get("/types", response_model=List[OntologyType])
async def list_types(layer: str = "") -> List[OntologyType]:
    """List ontology types（layer 过滤；L0/L1 为种子层）。"""
    items = await service.list_types(layer)
    if items is None:
        raise _unavailable()
    return items


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------


@router.get("/objects", response_model=List[OntologyObject])
async def list_objects(
    type_id: str = "",
    org_id: str = "",
    department_id: str = "",
    status: str = "",
    q: str = "",
    limit: int = 200,
) -> List[OntologyObject]:
    """List live objects（多条件 AND；q 模糊匹配 name）。"""
    items = await service.list_objects(
        type_id=type_id,
        org_id=org_id,
        department_id=department_id,
        status=status,
        keyword=q,
        limit=limit,
    )
    if items is None:
        raise _unavailable()
    return items


@router.post("/objects", status_code=201, response_model=OntologyObject)
async def create_object(payload: OntologyObject) -> OntologyObject:
    """Create one object（type 引用完整性校验；id 缺省生成）。"""
    try:
        obj = await service.create_object(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if obj is None:
        raise _unavailable()
    # 审计留痕：对象新建（操作者缺省管理面 admin）
    record_write_audit(
        tool_name="ontology.object.create",
        target=obj.id,
        actor_id=obj.owner_id or "admin",
        after=_object_snapshot(obj),
    )
    return obj


@router.get("/objects/{object_id}", response_model=OntologyObject)
async def get_object(object_id: str) -> OntologyObject:
    """Fetch one live object。"""
    obj = await service.get_object(object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    return obj


@router.patch("/objects/{object_id}", response_model=OntologyObject)
async def update_object(
    object_id: str,
    fields: Dict[str, Any],
) -> OntologyObject:
    """Patch whitelisted object fields（updated_at 恒前进）。"""
    prev = await service.get_object(object_id)
    if prev is None:
        raise HTTPException(status_code=404, detail="object not found")
    updated = await service.update_object(object_id, fields)
    if updated is None:
        raise _unavailable()
    # 审计留痕：字段级变更（更新前快照 vs 提交字段）
    record_write_audit(
        tool_name="ontology.object.update",
        target=object_id,
        actor_id=str(fields.get("owner_id") or "admin"),
        before=_object_snapshot(prev),
        after={
            "fields": sorted(fields),
            **_object_snapshot(updated),
        },
    )
    return updated


@router.delete("/objects/{object_id}", status_code=204)
async def delete_object(object_id: str) -> None:
    """Logical-delete one object（幂等：已删/不存在均 204）。"""
    prev = await service.get_object(object_id)
    deleted = await service.soft_delete_object(object_id)
    if deleted is None:
        raise _unavailable()
    # 审计留痕：对象逻辑删除（存在过才记，幂等重放不留重复审计行）
    if prev is not None:
        record_write_audit(
            tool_name="ontology.object.delete",
            target=object_id,
            actor_id=prev.owner_id or "admin",
            before=_object_snapshot(prev),
        )


@router.post("/objects/{object_id}/transitions")
async def apply_transition(
    object_id: str,
    body: TransitionBody,
) -> dict:
    """记录一次状态迁移并推进对象 state（留档先行）。"""
    try:
        trn = await service.apply_transition(
            object_id,
            body.to_state,
            trigger_type=body.trigger_type,
            operator=body.operator,
            permission=body.permission,
            preconditions=body.preconditions,
            postconditions=body.postconditions,
            audit_required=body.audit_required,
        )
    except ValueError as exc:
        # object_id 在路径上：资源不存在升 404（REST 语义）
        raise _bad_request(exc, path_resource=True) from exc
    if trn is None:
        raise _unavailable()
    obj = await service.get_object(object_id)
    return {"transition": trn.model_dump(mode="json"), "object": obj}


@router.get("/objects/{object_id}/relations")
async def list_object_relations(object_id: str) -> dict:
    """List both directions of relations for one object。"""
    if await service.get_object(object_id) is None:
        raise HTTPException(status_code=404, detail="object not found")
    outbound = await service.list_relations(from_id=object_id)
    inbound = await service.list_relations(to_id=object_id)
    if outbound is None or inbound is None:
        raise _unavailable()
    return {
        "outbound": [rel.model_dump(mode="json") for rel in outbound],
        "inbound": [rel.model_dump(mode="json") for rel in inbound],
    }


# ---------------------------------------------------------------------------
# relations
# ---------------------------------------------------------------------------


@router.post("/relations", status_code=201, response_model=OntologyRelation)
async def create_relation(payload: OntologyRelation) -> OntologyRelation:
    """Create one directed relation（端点存在性校验）。"""
    try:
        rel = await service.create_relation(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if rel is None:
        raise _unavailable()
    # 审计留痕：关系新建
    record_write_audit(
        tool_name="ontology.relation.create",
        target=rel.id,
        actor_id="admin",
        after=_relation_snapshot(rel),
    )
    return rel


@router.get("/relations", response_model=List[OntologyRelation])
async def list_relations(
    from_id: str = "",
    to_id: str = "",
    type: str = "",
    limit: int = 200,
) -> List[OntologyRelation]:
    """List relations（端点/类型过滤）。"""
    items = await service.list_relations(
        from_id=from_id,
        to_id=to_id,
        rel_type=type,
        limit=limit,
    )
    if items is None:
        raise _unavailable()
    return items


@router.delete("/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: str) -> None:
    """Remove one relation（不存在亦 204，幂等）。"""
    deleted = await service.delete_relation(relation_id)
    if deleted is None:
        raise _unavailable()
    # 审计留痕：关系删除（真删了行才记，幂等重放不留重复审计行）
    if deleted is True:
        record_write_audit(
            tool_name="ontology.relation.delete",
            target=relation_id,
            actor_id="admin",
        )


# ---------------------------------------------------------------------------
# transitions（留档查询）
# ---------------------------------------------------------------------------


@router.get("/transitions")
async def list_transitions(
    object_id: str,
    limit: int = 100,
) -> List[dict]:
    """List transition records of one object（新→旧）。"""
    items = await service.list_transitions(object_id, limit)
    if items is None:
        raise _unavailable()
    return [trn.model_dump(mode="json") for trn in items]


# ---------------------------------------------------------------------------
# rules / actions（留档 CRUD）
# ---------------------------------------------------------------------------


@router.post("/rules", status_code=201, response_model=OntologyRule)
async def create_rule(payload: OntologyRule) -> OntologyRule:
    """Create one rule record（仅建模留档）。"""
    try:
        rule = await service.create_rule(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if rule is None:
        raise _unavailable()
    return rule


@router.get("/rules", response_model=List[OntologyRule])
async def list_rules(
    object_type: str = "",
    limit: int = 200,
) -> List[OntologyRule]:
    """List rule records（priority 升序）。"""
    items = await service.list_rules(object_type, limit)
    if items is None:
        raise _unavailable()
    return items


@router.post("/actions", status_code=201, response_model=OntologyAction)
async def create_action(payload: OntologyAction) -> OntologyAction:
    """Create one action record（仅建模留档）。"""
    try:
        action = await service.create_action(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if action is None:
        raise _unavailable()
    return action


@router.get("/actions", response_model=List[OntologyAction])
async def list_actions(
    object_type: str = "",
    limit: int = 200,
) -> List[OntologyAction]:
    """List action records。"""
    items = await service.list_actions(object_type, limit)
    if items is None:
        raise _unavailable()
    return items


# ---------------------------------------------------------------------------
# kb_object_links（知识 ↔ 本体互引）
# ---------------------------------------------------------------------------


@router.post("/links", status_code=201, response_model=KbObjectLink)
async def create_link(payload: KbObjectLink) -> KbObjectLink:
    """Create one knowledge-object link（对象存在性校验）。"""
    try:
        link = await service.create_link(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if link is None:
        raise _unavailable()
    # 审计留痕：知识↔本体互引新建
    record_write_audit(
        tool_name="ontology.link.create",
        target=link.id,
        actor_id="admin",
        after=_link_snapshot(link),
    )
    return link


@router.get("/links", response_model=List[KbObjectLink])
async def list_links(
    document_id: str = "",
    object_id: str = "",
) -> List[KbObjectLink]:
    """List links（文档侧/对象侧二选一；两者皆空返回空列表）。"""
    items = await service.list_links(
        document_id=document_id,
        object_id=object_id,
    )
    if items is None:
        raise _unavailable()
    return items


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: str) -> None:
    """Remove one link（不存在亦 204，幂等）。"""
    deleted = await service.delete_link(link_id)
    if deleted is None:
        raise _unavailable()
    # 审计留痕：互引删除（真删了行才记，幂等重放不留重复审计行）
    if deleted is True:
        record_write_audit(
            tool_name="ontology.link.delete",
            target=link_id,
            actor_id="admin",
        )


__all__ = ["router", "TransitionBody"]
