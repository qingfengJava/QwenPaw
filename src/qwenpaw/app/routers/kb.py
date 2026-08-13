# -*- coding: utf-8 -*-
"""Employee-facing knowledge base API (M4-5).

Employees list/search the bases they can access (ACL-filtered) and
manage documents in their own personal bases.  Cross-scope
administration lives under ``/api/admin/kb``.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..kb.models import SCOPE_PERSONAL, KnowledgeBase
from ..kb.service import get_kb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


class KbView(BaseModel):
    id: str
    name: str
    scope: str
    owner_id: str = ""
    team_id: str = ""
    description: str = ""


class CreateKbBody(BaseModel):
    name: str
    description: str = ""


class IngestBody(BaseModel):
    text: str
    title: str = ""
    source: str = ""


class SearchBody(BaseModel):
    query: str
    kb_id: Optional[str] = None  # None = search every accessible base
    top_k: int = Field(default=5, ge=1, le=50)


class SearchHit(BaseModel):
    kb_id: str
    kb_name: str
    doc_id: str
    title: str
    text: str
    score: float


class SearchResponse(BaseModel):
    hits: List[SearchHit] = Field(default_factory=list)


def _caller(request: Request) -> str:
    return getattr(request.state, "user", None) or ""


def _access_kwargs(username: str) -> dict:
    from ..rbac.deps import _resolve_flat_role
    from ..rbac.store import get_rbac_store

    flat_role = _resolve_flat_role(username) if username else ""
    store = get_rbac_store()
    return {
        "flat_role": flat_role,
        "user_roles": store.roles_for_user(username, flat_role),
        "user_teams": store.teams_for_user(username),
    }


def _view(kb: KnowledgeBase) -> KbView:
    return KbView(
        id=kb.id,
        name=kb.name,
        scope=kb.scope,
        owner_id=kb.owner_id,
        team_id=kb.team_id,
        description=kb.description,
    )


@router.get("", response_model=List[KbView])
async def list_accessible(request: Request) -> List[KbView]:
    """List every knowledge base the caller may read."""
    username = _caller(request)
    service = get_kb_service()
    kbs = service.accessible_kbs(username, **_access_kwargs(username))
    return [_view(kb) for kb in kbs]


@router.post("", status_code=201, response_model=KbView)
async def create_personal_kb(
    body: CreateKbBody,
    request: Request,
) -> KbView:
    """Create a personal knowledge base owned by the caller."""
    username = _caller(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    kb = get_kb_service().create_kb(
        body.name,
        scope=SCOPE_PERSONAL,
        owner_id=username,
        description=body.description,
    )
    if kb is None:
        raise HTTPException(status_code=400, detail="invalid kb payload")
    return _view(kb)


def _get_accessible_kb(kb_id: str, username: str) -> KnowledgeBase:
    service = get_kb_service()
    kb = service.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="kb not found")
    if not service.can_access(kb, username, **_access_kwargs(username)):
        raise HTTPException(status_code=403, detail="no access to this kb")
    return kb


@router.post("/{kb_id}/documents", status_code=201)
async def ingest_document(
    kb_id: str,
    body: IngestBody,
    request: Request,
) -> dict:
    """Ingest text into a kb. Personal bases: owner only; other scopes
    require the kb:write permission (team/enterprise administration)."""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    if kb.scope == SCOPE_PERSONAL and kb.owner_id != username:
        raise HTTPException(status_code=403, detail="owner only")
    if kb.scope != SCOPE_PERSONAL:
        from ..rbac import PERM_KB_WRITE
        from ..rbac.deps import _resolve_flat_role
        from ..rbac.store import get_rbac_store

        flat_role = _resolve_flat_role(username) if username else ""
        if not get_rbac_store().user_has_permission(
            username,
            PERM_KB_WRITE,
            flat_role=flat_role,
        ):
            raise HTTPException(status_code=403, detail="kb:write required")
    doc = get_kb_service().ingest_text(
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


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
) -> None:
    """Remove one document. Same permission rule as ingestion."""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    if kb.scope == SCOPE_PERSONAL and kb.owner_id != username:
        raise HTTPException(status_code=403, detail="owner only")
    if not get_kb_service().delete_document(doc_id):
        raise HTTPException(status_code=404, detail="document not found")


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchBody, request: Request) -> SearchResponse:
    """Hybrid search across one or all accessible knowledge bases."""
    username = _caller(request)
    service = get_kb_service()
    if body.kb_id:
        kbs = [_get_accessible_kb(body.kb_id, username)]
    else:
        kbs = service.accessible_kbs(username, **_access_kwargs(username))
    hits: list[SearchHit] = []
    for kb in kbs:
        for chunk, score in service.search(
            kb.id,
            body.query,
            top_k=body.top_k,
        ):
            hits.append(
                SearchHit(
                    kb_id=kb.id,
                    kb_name=kb.name,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    text=chunk.text,
                    score=score,
                ),
            )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return SearchResponse(hits=hits[: body.top_k])
