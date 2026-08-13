# -*- coding: utf-8 -*-
"""Knowledge base service (M4-5): registry, ingestion, retrieval, ACL.

Storage layout under ``SECRET_DIR`` (file-backed, matching the M4
management-plane pattern)::

    kb_registry.json            # KnowledgeBase + document registry
    kb_data/<kb_id>/chunks.jsonl

ACL resolution order for one user on one kb:

1. platform admins (flat ``admin``) see everything;
2. ``personal`` scope: the owner only;
3. ``team`` scope: members of ``team_id``;
4. ``enterprise`` scope: every authenticated user;
5. explicit grants (roles/users/teams) extend any scope.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from ...constant import SECRET_DIR
from .models import (
    SCOPE_ENTERPRISE,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    VALID_SCOPES,
    KbChunk,
    KbDocumentMeta,
    KbRegistry,
    KnowledgeBase,
)
from .search import search_chunks

logger = logging.getLogger(__name__)

REGISTRY_FILE = SECRET_DIR / "kb_registry.json"
DATA_DIR = SECRET_DIR / "kb_data"

# Chunking: split on blank lines, pack paragraphs into ~800-char chunks
# with a small overlap so sentences crossing boundaries stay intact.
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def chunk_text(text: str) -> List[str]:
    """Split *text* into paragraph-packed chunks of ~800 chars."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= _CHUNK_SIZE:
            current = f"{current}\n\n{para}"
        else:
            chunks.append(current)
            overlap = current[-_CHUNK_OVERLAP:] if _CHUNK_OVERLAP else ""
            current = f"{overlap}{para}" if overlap else para
    if current:
        chunks.append(current)
    # Hard-split any chunk still beyond 4x the target (no blank lines).
    result: list[str] = []
    for chunk in chunks:
        while len(chunk) > _CHUNK_SIZE * 4:
            result.append(chunk[: _CHUNK_SIZE * 4])
            chunk = chunk[_CHUNK_SIZE * 4 - _CHUNK_OVERLAP :]
        result.append(chunk)
    return [c for c in result if c.strip()]


class KbService:
    """Knowledge base registry + per-kb chunk store."""

    def __init__(
        self,
        registry_path: Path | str = REGISTRY_FILE,
        data_dir: Path | str = DATA_DIR,
    ) -> None:
        self._registry_path = Path(registry_path)
        self._data_dir = Path(data_dir)
        self._lock = threading.Lock()
        self._cache_valid = False
        self._cache_key: Optional[int] = None
        self._cache_data: Optional[KbRegistry] = None
        # Per-kb chunk cache: kb_id -> (mtime_ns, chunks).
        self._chunk_cache: dict[str, tuple[Optional[int], List[KbChunk]]] = {}

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> KbRegistry:
        try:
            cache_key: Optional[int] = self._registry_path.stat().st_mtime_ns
        except OSError:
            cache_key = None
        if self._cache_valid and cache_key == self._cache_key:
            return self._cache_data  # type: ignore[return-value]
        data = KbRegistry()
        if self._registry_path.is_file():
            try:
                with open(
                    self._registry_path,
                    "r",
                    encoding="utf-8",
                ) as fh:
                    data = KbRegistry.model_validate(json.load(fh))
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.error(
                    "Failed to load kb registry %s: %s",
                    self._registry_path,
                    exc,
                )
        self._cache_valid = True
        self._cache_key, self._cache_data = cache_key, data
        return data

    def _save(self, data: KbRegistry) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(self._registry_path.parent, 0o700)
        with open(self._registry_path, "w", encoding="utf-8") as fh:
            json.dump(
                data.model_dump(mode="json"),
                fh,
                indent=2,
                ensure_ascii=False,
            )
        _chmod_best_effort(self._registry_path, 0o600)
        try:
            self._cache_key = self._registry_path.stat().st_mtime_ns
        except OSError:
            self._cache_key = None
        self._cache_data = data
        self._cache_valid = True

    def _chunks_path(self, kb_id: str) -> Path:
        return self._data_dir / kb_id / "chunks.jsonl"

    def _load_chunks(self, kb_id: str) -> List[KbChunk]:
        path = self._chunks_path(kb_id)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        cached = self._chunk_cache.get(kb_id)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        chunks: list[KbChunk] = []
        if mtime is not None:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            chunks.append(KbChunk.model_validate_json(line))
            except (OSError, ValueError) as exc:
                logger.error("Failed to read kb chunks %s: %s", path, exc)
        self._chunk_cache[kb_id] = (mtime, chunks)
        return chunks

    def _save_chunks(self, kb_id: str, chunks: List[KbChunk]) -> None:
        path = self._chunks_path(kb_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for chunk in chunks:
                fh.write(
                    chunk.model_dump_json() + "\n",
                )
        try:
            mtime: Optional[int] = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        self._chunk_cache[kb_id] = (mtime, chunks)

    # ------------------------------------------------------------------
    # knowledge base CRUD
    # ------------------------------------------------------------------

    def create_kb(
        self,
        name: str,
        *,
        scope: str = SCOPE_PERSONAL,
        owner_id: str = "",
        team_id: str = "",
        description: str = "",
    ) -> Optional[KnowledgeBase]:
        name = name.strip()
        if not name or scope not in VALID_SCOPES:
            return None
        if scope == SCOPE_PERSONAL and not owner_id:
            return None
        if scope == SCOPE_TEAM and not team_id:
            return None
        kb = KnowledgeBase(
            id=f"kb_{uuid.uuid4().hex[:12]}",
            name=name,
            scope=scope,
            owner_id=owner_id,
            team_id=team_id,
            description=description.strip(),
        )
        with self._lock:
            data = self._load()
            data.knowledge_bases[kb.id] = kb
            self._save(data)
        return kb

    def get_kb(self, kb_id: str) -> Optional[KnowledgeBase]:
        return self._load().knowledge_bases.get(kb_id)

    def update_grants(
        self,
        kb_id: str,
        *,
        roles: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
        teams: Optional[List[str]] = None,
    ) -> Optional[KnowledgeBase]:
        """Replace a kb's explicit grant lists (admin API)."""
        with self._lock:
            data = self._load()
            kb = data.knowledge_bases.get(kb_id)
            if kb is None:
                return None
            if roles is not None:
                kb.grants_roles = list(roles)
            if users is not None:
                kb.grants_users = list(users)
            if teams is not None:
                kb.grants_teams = list(teams)
            self._save(data)
        return kb

    def list_kbs(self) -> List[KnowledgeBase]:
        return list(self._load().knowledge_bases.values())

    def delete_kb(self, kb_id: str) -> bool:
        with self._lock:
            data = self._load()
            if kb_id not in data.knowledge_bases:
                return False
            del data.knowledge_bases[kb_id]
            for doc_id in [
                d for d, doc in data.documents.items() if doc.kb_id == kb_id
            ]:
                del data.documents[doc_id]
            self._save(data)
        chunks_path = self._chunks_path(kb_id)
        try:
            chunks_path.unlink(missing_ok=True)
            chunks_path.parent.rmdir()
        except OSError:
            pass
        self._chunk_cache.pop(kb_id, None)
        return True

    # ------------------------------------------------------------------
    # ACL
    # ------------------------------------------------------------------

    def can_access(
        self,
        kb: KnowledgeBase,
        username: str,
        *,
        flat_role: str = "",
        user_roles: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
    ) -> bool:
        """Whether *username* may read *kb*."""
        if flat_role == "admin":
            return True
        if username and username in kb.grants_users:
            return True
        roles = user_roles or []
        if any(role in kb.grants_roles for role in roles):
            return True
        teams = user_teams or []
        if any(team in kb.grants_teams for team in teams):
            return True
        if kb.scope == SCOPE_PERSONAL:
            return bool(username) and username == kb.owner_id
        if kb.scope == SCOPE_TEAM:
            return bool(kb.team_id) and kb.team_id in teams
        if kb.scope == SCOPE_ENTERPRISE:
            return bool(username)
        return False

    def accessible_kbs(
        self,
        username: str,
        *,
        flat_role: str = "",
        user_roles: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
    ) -> List[KnowledgeBase]:
        """All knowledge bases visible to *username*."""
        return [
            kb
            for kb in self.list_kbs()
            if self.can_access(
                kb,
                username,
                flat_role=flat_role,
                user_roles=user_roles,
                user_teams=user_teams,
            )
        ]

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------

    def ingest_text(
        self,
        kb_id: str,
        text: str,
        *,
        title: str = "",
        source: str = "",
        embeddings: Optional[List[List[float]]] = None,
    ) -> Optional[KbDocumentMeta]:
        """Chunk *text* and append it to the kb's store.

        *embeddings* (one vector per chunk, same order) is optional —
        callers compute it when an embedding model is configured.
        """
        if self.get_kb(kb_id) is None or not text.strip():
            return None
        pieces = chunk_text(text)
        if not pieces:
            return None
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        with self._lock:
            chunks = list(self._load_chunks(kb_id))
            base_seq = len(chunks)
            for index, piece in enumerate(pieces):
                embedding = None
                if embeddings and index < len(embeddings):
                    embedding = embeddings[index]
                chunks.append(
                    KbChunk(
                        chunk_id=f"{doc_id}_{index}",
                        kb_id=kb_id,
                        doc_id=doc_id,
                        title=title,
                        seq=base_seq + index,
                        text=piece,
                        embedding=embedding,
                    ),
                )
            self._save_chunks(kb_id, chunks)
            data = self._load()
            doc = KbDocumentMeta(
                doc_id=doc_id,
                kb_id=kb_id,
                title=title or pieces[0][:40],
                source=source,
                chunk_count=len(pieces),
            )
            data.documents[doc_id] = doc
            self._save(data)
        return doc

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            data = self._load()
            doc = data.documents.get(doc_id)
            if doc is None:
                return False
            del data.documents[doc_id]
            chunks = [
                c for c in self._load_chunks(doc.kb_id)
                if c.doc_id != doc_id
            ]
            self._save_chunks(doc.kb_id, chunks)
            self._save(data)
        return True

    def list_documents(self, kb_id: str) -> List[KbDocumentMeta]:
        return [
            doc
            for doc in self._load().documents.values()
            if doc.kb_id == kb_id
        ]

    # ------------------------------------------------------------------
    # retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        kb_id: str,
        query: str,
        *,
        top_k: int = 5,
        query_embedding: Optional[List[float]] = None,
    ) -> List[tuple[KbChunk, float]]:
        """Rank chunks of one kb. ACL is the caller's responsibility
        (see :meth:`accessible_kbs`)."""
        chunks = self._load_chunks(kb_id)
        return search_chunks(
            chunks,
            query,
            query_embedding=query_embedding,
            top_k=top_k,
        )


_default_service: Optional[KbService] = None


def get_kb_service() -> KbService:
    """Return the process-wide default KB service (lazy singleton)."""
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = KbService()
    return _default_service


def reset_kb_service() -> None:
    """Drop the singleton (tests)."""
    global _default_service  # noqa: PLW0603
    _default_service = None
