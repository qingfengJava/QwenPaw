# -*- coding: utf-8 -*-
"""Enterprise knowledge bases (M4-5): three-scope shared corpora.

Personal (owner-private), team (member-shared) and enterprise (all
authenticated users) libraries; retrieval is BM25 with optional vector
fusion (RRF).  Long-term memory stays per-user and separate — knowledge
bases hold shared enterprise/team corpora, never private memory.
"""
from .models import (
    SCOPE_ENTERPRISE,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    KbChunk,
    KbDocumentMeta,
    KnowledgeBase,
)
from .service import KbService, chunk_text, get_kb_service, reset_kb_service

__all__ = [
    "SCOPE_ENTERPRISE",
    "SCOPE_PERSONAL",
    "SCOPE_TEAM",
    "KbChunk",
    "KbDocumentMeta",
    "KbService",
    "KnowledgeBase",
    "chunk_text",
    "get_kb_service",
    "reset_kb_service",
]
