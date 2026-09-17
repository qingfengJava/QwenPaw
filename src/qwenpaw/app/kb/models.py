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
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

SCOPE_PERSONAL = "personal"
SCOPE_TEAM = "team"
SCOPE_ENTERPRISE = "enterprise"
VALID_SCOPES = frozenset({SCOPE_PERSONAL, SCOPE_TEAM, SCOPE_ENTERPRISE})

#: 检索引擎路由（``kb_spaces.engine``，spec §5；auto = 按库规模自动选）
ENGINE_AUTO = "auto"
ENGINE_PGVECTOR = "pgvector"
ENGINE_MILVUS = "milvus"
VALID_ENGINES = frozenset({ENGINE_AUTO, ENGINE_PGVECTOR, ENGINE_MILVUS})

#: 文档来源（``kb_documents.source``）
SOURCE_MANUAL = "manual"
SOURCE_UPLOAD = "upload"
SOURCE_URL = "url"
VALID_SOURCES = frozenset({SOURCE_MANUAL, SOURCE_UPLOAD, SOURCE_URL})

#: 摄入状态机（``kb_documents.ingest_status``，文档级：pending→processing→ready/failed）
INGEST_PENDING = "pending"
INGEST_PROCESSING = "processing"
INGEST_READY = "ready"
INGEST_FAILED = "failed"
VALID_INGEST_STATUSES = frozenset(
    {
        INGEST_PENDING,
        INGEST_PROCESSING,
        INGEST_READY,
        INGEST_FAILED,
    },
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_enum_value(
    field: str,
    allowed: frozenset,
    value: str,
) -> str:
    """Assert one enum-ish column stays inside its DB CHECK value set.

    0034 给 ``scope`` / ``engine`` / ``source`` / ``ingest_status`` 都建了
    CHECK 约束，但撞到约束意味着一次往返后才拿到 ``IntegrityError``；模型层
    先校一道，让调用方拿到可读的 ValidationError。
    """
    if value not in allowed:
        raise ValueError(
            f"{field} 取值非法：{value!r}，仅允许 {sorted(allowed)}",
        )
    return value


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


# ---------------------------------------------------------------------------
# PG 平面读模型（M6：字段与 alembic 0034 逐列对齐）
#
# 旧 ``KnowledgeBase`` 保留为 json 后端兼容模型；``KbSpace`` / ``KbDocument``
# 是 PG 权威平面的模型，由 ``KbService`` 门面统一向外转换，二者不共存于
# 同一条读写链路上。
# ---------------------------------------------------------------------------


class KbSpace(BaseModel):
    """One knowledge space（``kb_spaces`` 行）。"""

    id: str
    name: str
    description: str = ""
    scope: str = SCOPE_PERSONAL
    owner_id: str = ""
    team_id: str = ""
    # 超出 scope 的显式授权扩展：{"roles": [], "users": [], "teams": []}
    grants: Dict[str, Any] = Field(default_factory=dict)
    embedding_model: str = ""
    engine: str = ENGINE_AUTO
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        # 把 0034 的 ck_kb_spaces_scope 前移到模型层，不让非法值穿到 DB 才炸
        return _require_enum_value("scope", VALID_SCOPES, value)

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        # 同上：ck_kb_spaces_engine 的模型侧镜像
        return _require_enum_value("engine", VALID_ENGINES, value)


class KbDocument(BaseModel):
    """One knowledge document（``kb_documents`` 行，知识内容的权威源）。"""

    id: str
    space_id: str
    # 库内唯一路径；写入前必须非空（否则撞 uq_kb_documents_path 部分唯一索引）
    path: str = ""
    title: str = ""
    content_md: str = ""
    content_hash: str = ""
    source: str = SOURCE_MANUAL
    source_meta: Dict[str, Any] = Field(default_factory=dict)
    ingest_status: str = INGEST_READY
    error: str = ""
    is_delete: bool = False
    updated_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        # 镜像 ck_kb_documents_source
        return _require_enum_value("source", VALID_SOURCES, value)

    @field_validator("ingest_status")
    @classmethod
    def _validate_ingest_status(cls, value: str) -> str:
        # 镜像 ck_kb_documents_ingest_status
        return _require_enum_value(
            "ingest_status",
            VALID_INGEST_STATUSES,
            value,
        )
