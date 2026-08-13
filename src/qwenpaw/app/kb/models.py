# -*- coding: utf-8 -*-
"""Knowledge base domain models (M4-5).

Three scopes, per the plan:

- ``personal``   — private to ``owner_id`` (one user's library)
- ``team``       — shared with members of ``team_id``
- ``enterprise`` — shared with every authenticated user

Explicit ``grants`` (roles/users/teams) extend the scope ACL, mirroring
the M4-3 agent/model grant semantics: absent grants mean "scope only".

Chunks are stored per-kb as JSONL (``kb_data/<kb_id>/chunks.jsonl``);
embeddings are optional (computed when an embedding model is configured)
so the BM25 path always works.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

SCOPE_PERSONAL = "personal"
SCOPE_TEAM = "team"
SCOPE_ENTERPRISE = "enterprise"
VALID_SCOPES = frozenset({SCOPE_PERSONAL, SCOPE_TEAM, SCOPE_ENTERPRISE})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBase(BaseModel):
    """One knowledge base registry entry."""

    id: str
    name: str
    scope: str = SCOPE_PERSONAL
    owner_id: str = ""  # personal scope: the owning user
    team_id: str = ""  # team scope: the owning team
    description: str = ""
    # Explicit ACL extension beyond the scope (roles/users/teams).
    grants_roles: List[str] = Field(default_factory=list)
    grants_users: List[str] = Field(default_factory=list)
    grants_teams: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class KbDocumentMeta(BaseModel):
    """One ingested document's registry entry."""

    doc_id: str
    kb_id: str
    title: str = ""
    source: str = ""
    chunk_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class KbChunk(BaseModel):
    """One retrievable text chunk."""

    chunk_id: str
    kb_id: str
    doc_id: str
    title: str = ""
    seq: int = 0
    text: str
    embedding: Optional[List[float]] = None


class KbRegistry(BaseModel):
    """``kb_registry.json`` root document."""

    version: int = 1
    knowledge_bases: Dict[str, KnowledgeBase] = Field(default_factory=dict)
    documents: Dict[str, KbDocumentMeta] = Field(default_factory=dict)
