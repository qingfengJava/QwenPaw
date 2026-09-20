# -*- coding: utf-8 -*-
"""Admin knowledge base management API (M4-5/M4-6)."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...kb.bindings import delete_space_bindings
from ...kb.models import (
    VALID_SCOPES,
    KnowledgeBase,
)
from ...kb.service import get_kb_service
from ...rbac import require_perm
from ...rbac.models import PERM_ADMIN_KB
from ...write_audit import record_write_audit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/kb",
    tags=["admin-kb"],
    dependencies=[Depends(require_perm(PERM_ADMIN_KB))],
)


class KbBody(BaseModel):
    name: str
    scope: str
    owner_id: str = ""
    team_id: str = ""
    org_id: str = "default"
    description: str = ""
    grants_roles: List[str] = Field(default_factory=list)
    grants_users: List[str] = Field(default_factory=list)
    grants_teams: List[str] = Field(default_factory=list)


class AdminIngestBody(BaseModel):
    text: str
    title: str = ""
    source: str = ""


@router.get("", response_model=List[KnowledgeBase])
async def list_all_kbs() -> List[KnowledgeBase]:
    """List every knowledge base (unfiltered)."""
    return get_kb_service().list_kbs()


@router.post("", status_code=201, response_model=KnowledgeBase)
async def create_kb(body: KbBody) -> KnowledgeBase:
    """Create a knowledge base of any scope."""
    service = get_kb_service()
    kb = service.create_kb(
        body.name,
        scope=body.scope,
        owner_id=body.owner_id,
        team_id=body.team_id,
        org_id=body.org_id,
        description=body.description,
    )
    if kb is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid kb: scope must be one of "
                f"{sorted(VALID_SCOPES)}, personal needs owner_id, "
                "team needs team_id"
            ),
        )
    # Attach grants when provided.
    if body.grants_roles or body.grants_users or body.grants_teams:
        updated = service.update_grants(
            kb.id,
            roles=body.grants_roles,
            users=body.grants_users,
            teams=body.grants_teams,
        )
        if updated is not None:
            kb = updated
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: str) -> None:
    """Delete a knowledge base with all its chunks."""
    if not get_kb_service().delete_kb(kb_id):
        raise HTTPException(status_code=404, detail="kb not found")
    # 删库同步回收 json 态绑定行（0034 无外键，孤绑定会在绑定列表造出脏读）；
    # pg/dual 态 delete_space_bindings 自身 no-op——绑定由门面 delete_kb 路由到
    # KbPgStore.delete_space 时同事务回收（T8 门面统一已落地该 pg 路由）
    await delete_space_bindings(kb_id)


@router.post("/{kb_id}/documents", status_code=201)
async def ingest_document(kb_id: str, body: AdminIngestBody) -> dict:
    """Ingest text into any knowledge base."""
    service = get_kb_service()
    if service.get_kb(kb_id) is None:
        raise HTTPException(status_code=404, detail="kb not found")
    doc = service.ingest_text(
        kb_id,
        body.text,
        title=body.title,
        source=body.source,
    )
    if doc is None:
        raise HTTPException(status_code=400, detail="empty document")
    return {
        "doc_id": doc.doc_id,
        "kb_id": doc.kb_id,
        "chunk_count": doc.chunk_count,
    }


@router.get("/{kb_id}/documents")
async def list_documents(kb_id: str) -> List[dict]:
    """List documents of one kb（T3 起携带生命周期/分类字段）。"""
    service = get_kb_service()
    if service.get_kb(kb_id) is None:
        raise HTTPException(status_code=404, detail="kb not found")
    return [
        {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "source": doc.source,
            "chunk_count": doc.chunk_count,
            "knowledge_status": doc.knowledge_status,
            "valid_from": (
                doc.valid_from.isoformat() if doc.valid_from else None
            ),
            "valid_to": doc.valid_to.isoformat() if doc.valid_to else None,
            "created_at": doc.created_at.isoformat(),
        }
        for doc in service.list_documents(kb_id)
    ]


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(kb_id: str, doc_id: str) -> None:
    """Remove one document from a kb."""
    del kb_id  # doc_id is globally unique; kb_id is for the URL shape.
    if not get_kb_service().delete_document(doc_id):
        raise HTTPException(status_code=404, detail="document not found")


class SearchTestBody(BaseModel):
    """search-test 请求体（对齐员工面 SearchBody 风格，T11）。"""

    query: str
    kb_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)


@router.post("/search-test")
def search_test(body: SearchTestBody) -> dict:
    """检索调参透传：单库引擎 top-k + 得分明细（不叠加 ACL 收敛）。"""
    if not body.kb_id:
        raise HTTPException(status_code=400, detail="kb_id is required")
    service = get_kb_service()
    if service.get_kb(body.kb_id) is None:
        raise HTTPException(status_code=404, detail="kb not found")
    # P1-1 同一门控：dual 后端下三态 search 读 json 主面而 T11 写入走
    # pg 权威面，命中缺失会误导调参结论；json 部署请用员工面
    # /api/kb/search（json 引擎正常）。
    if not service.pg_ready():
        raise HTTPException(
            status_code=503,
            detail=(
                "search-test requires the pg backend (dual deployments "
                "read the json plane; use /api/kb/search instead)"
            ),
        )
    hits = [
        {
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "seq": chunk.seq,
            "title": chunk.title,
            "text": chunk.text,
            "score": score,
            "heading_path": chunk.heading_path,
        }
        for chunk, score in service.search(
            body.kb_id,
            body.query,
            top_k=body.top_k,
        )
    ]
    hits.sort(key=lambda hit: hit["score"], reverse=True)
    return {"kb_id": body.kb_id, "hits": hits[: body.top_k]}


# ------------------------------------------------------------------
# T3: LLM Wiki 知识层端点（管理面；权限已由 router 级 require_perm
# (PERM_ADMIN_KB) 收敛，生命周期/冲突全部走 pg 权威面）
# ------------------------------------------------------------------


class AdminReviewBody(BaseModel):
    action: str
    comment: str = ""
    reviewer: str = ""


class AdminMetaBody(BaseModel):
    """分类/有效期编辑体（全部可选，仅提供的字段会被更新）。"""

    domain: Optional[str] = None
    doc_type: Optional[str] = None
    confidence: Optional[float] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


def _admin_reviewer(body: AdminReviewBody) -> str:
    """审核人：请求体显式指定优先，缺省落 admin（管理面操作者）。"""
    return body.reviewer.strip() or "admin"


def _pg_or_503(kb_id: str) -> None:
    """pg 权威面守门（wiki 端点全部依赖 0046 表）。"""
    if not get_kb_service().pg_ready():
        raise HTTPException(
            status_code=503,
            detail="knowledge base PG plane unavailable (pg backend required)",
        )


@router.post("/{kb_id}/documents/{doc_id}/review")
def admin_review_document(
    kb_id: str,
    doc_id: str,
    body: AdminReviewBody,
) -> dict:
    """推进知识生命周期（submit/approve/reject/archive + 流水）。"""
    service = get_kb_service()
    _pg_or_503(kb_id)
    try:
        doc = service.pg_review_document(
            kb_id,
            doc_id,
            body.action,
            _admin_reviewer(body),
            body.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    # 审计留痕：生命周期推进（谁审核的、推进到哪个状态、备注）
    record_write_audit(
        tool_name="kb_review",
        target=f"{kb_id}:{doc_id}",
        actor_id=_admin_reviewer(body),
        after={
            "action": body.action,
            "knowledge_status": doc.knowledge_status,
            "reviewed_by": doc.reviewed_by,
            "comment": body.comment,
        },
    )
    return {
        "doc_id": doc.id,
        "kb_id": doc.space_id,
        "knowledge_status": doc.knowledge_status,
        "reviewed_by": doc.reviewed_by,
        "review_note": doc.review_note,
    }


@router.get("/{kb_id}/documents/{doc_id}/reviews")
def admin_list_reviews(kb_id: str, doc_id: str) -> List[dict]:
    """一份文档的审核流水（新→旧）。"""
    service = get_kb_service()
    _pg_or_503(kb_id)
    return [
        {
            "id": review.id,
            "action": review.action,
            "reviewer": review.reviewer,
            "comment": review.comment,
            "created_at": review.created_at.isoformat(),
        }
        for review in service.pg_list_reviews(kb_id, doc_id)
    ]


@router.patch("/{kb_id}/documents/{doc_id}/meta")
def admin_update_document_meta(
    kb_id: str,
    doc_id: str,
    body: AdminMetaBody,
) -> dict:
    """分类/有效期编辑（仅提供的字段被更新；白名单外 400）。"""
    service = get_kb_service()
    _pg_or_503(kb_id)
    fields: dict = {}
    if body.domain is not None:
        fields["domain"] = body.domain.strip()
    if body.doc_type is not None:
        fields["doc_type"] = body.doc_type.strip()
    if body.confidence is not None:
        fields["confidence"] = body.confidence
    for key in ("valid_from", "valid_to"):
        value = getattr(body, key)
        if value is not None:
            from datetime import datetime

            try:
                fields[key] = datetime.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} 需为 ISO 8601 时间：{value!r}",
                ) from exc
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    # 审计留痕的变更前快照：仅取将被更新的字段（查询失败不影响主流程）
    before_meta: dict = {}
    try:
        prev_doc, _ = service.pg_document_detail(kb_id, doc_id)
        if prev_doc is not None:
            for key in fields:
                before_meta[key] = str(getattr(prev_doc, key, ""))
    except Exception:  # noqa: BLE001 - before 快照失败不阻断更新
        before_meta = {}
    try:
        updated = service.pg_update_knowledge_meta(doc_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="document not found")
    # 审计留痕：分类/有效期变更（更新前字段值 vs 本次提交字段）
    record_write_audit(
        tool_name="kb_doc_meta.update",
        target=f"{kb_id}:{doc_id}",
        actor_id="admin",
        before=before_meta,
        after={key: str(value) for key, value in fields.items()},
    )
    return {"doc_id": doc_id, "updated": sorted(fields)}


@router.get("/{kb_id}/conflicts")
def admin_list_conflicts(kb_id: str, status: str = "") -> List[dict]:
    """库内知识冲突清单（status=open/resolved/空=全态）。"""
    service = get_kb_service()
    _pg_or_503(kb_id)
    return [
        {
            "id": conflict.id,
            "document_id_a": conflict.document_id_a,
            "document_id_b": conflict.document_id_b,
            "conflict_type": conflict.conflict_type,
            "priority": conflict.priority,
            "resolution_status": conflict.resolution_status,
            "resolved_by": conflict.resolved_by,
            "created_at": conflict.created_at.isoformat(),
        }
        for conflict in service.pg_list_conflicts(kb_id, status=status)
    ]


@router.post("/{kb_id}/conflicts/{conflict_id}/resolve")
def admin_resolve_conflict(
    kb_id: str,
    conflict_id: str,
) -> dict:
    """解决一个 open 冲突（不存在/已解决合并 404 语义）。"""
    del kb_id  # 冲突主键全局唯一；kb_id 仅为 URL 形态一致性
    service = get_kb_service()
    if not service.pg_resolve_conflict(conflict_id, "admin"):
        raise HTTPException(status_code=404, detail="open conflict not found")
    # 审计留痕：冲突裁决（管理者面操作者缺省 admin）
    record_write_audit(
        tool_name="kb_conflict.resolve",
        target=conflict_id,
        actor_id="admin",
        after={"resolution_status": "resolved"},
    )
    return {"id": conflict_id, "resolution_status": "resolved"}


@router.post("/{kb_id}/documents/{doc_id}/conflicts/detect")
def admin_detect_conflicts(kb_id: str, doc_id: str) -> dict:
    """触发规则冲突检测（duplicate_title），返回本次新建候选。"""
    service = get_kb_service()
    _pg_or_503(kb_id)
    created = service.pg_detect_conflicts(kb_id, doc_id)
    return {
        "kb_id": kb_id,
        "doc_id": doc_id,
        "created": [
            {
                "id": conflict.id,
                "document_id_b": conflict.document_id_b,
                "priority": conflict.priority,
            }
            for conflict in created
        ],
    }


@router.post("/{kb_id}/documents/{doc_id}/wiki-suggest")
async def admin_wiki_suggest(kb_id: str, doc_id: str) -> dict:
    """LLM 结构化建议（摘要/域/类型候选；只返回候选，不落库）。"""
    from ...kb.wiki import suggest_wiki_meta

    service = get_kb_service()
    _pg_or_503(kb_id)
    doc, _ = service.pg_document_detail(kb_id, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    candidate = await suggest_wiki_meta(doc.content_md)
    if candidate is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "wiki suggestion unavailable (no chat model configured "
                "or model call failed)"
            ),
        )
    return {"doc_id": doc.id, "candidate": candidate}
