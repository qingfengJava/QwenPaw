# -*- coding: utf-8 -*-
"""Admin knowledge base management API (M4-5/M4-6)."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...kb.bindings import delete_space_bindings
from ...kb.models import VALID_SCOPES, KnowledgeBase
from ...kb.service import get_kb_service
from ...rbac import require_perm
from ...rbac.models import PERM_ADMIN_KB

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
    """List documents of one kb."""
    service = get_kb_service()
    if service.get_kb(kb_id) is None:
        raise HTTPException(status_code=404, detail="kb not found")
    return [
        {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "source": doc.source,
            "chunk_count": doc.chunk_count,
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
