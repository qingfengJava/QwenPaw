# -*- coding: utf-8 -*-
"""Knowledge base domain models (M4-5).

Three scopes, per the plan:

- ``personal``   — private to ``owner_id`` (one user's library)
- ``team``       — shared with members of ``team_id``
- ``org``        — shared across one org (the tenant boundary, 0044)
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
SCOPE_ORG = "org"
SCOPE_ENTERPRISE = "enterprise"
VALID_SCOPES = frozenset(
    {SCOPE_PERSONAL, SCOPE_TEAM, SCOPE_ORG, SCOPE_ENTERPRISE},
)

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

#: 知识生命周期（``kb_documents.knowledge_status``，0046；LLM Wiki 层）。
#: 与 ingest_status 正交：ingest 面答「切片索引就绪吗」，knowledge 面答
#: 「内容可信可检吗」——检索默认只出 published 且在有效期内的文档。
KNOWLEDGE_DRAFT = "draft"
KNOWLEDGE_IN_REVIEW = "in_review"
KNOWLEDGE_PUBLISHED = "published"
KNOWLEDGE_ARCHIVED = "archived"
VALID_KNOWLEDGE_STATUSES = frozenset(
    {
        KNOWLEDGE_DRAFT,
        KNOWLEDGE_IN_REVIEW,
        KNOWLEDGE_PUBLISHED,
        KNOWLEDGE_ARCHIVED,
    },
)

#: 文档类型（``kb_documents.doc_type``，对齐方案 §5.2 域内标准结构）
DOC_TYPE_DOC = "doc"
DOC_TYPE_PROCESS = "process"
DOC_TYPE_CASE = "case"
DOC_TYPE_QA = "qa"
DOC_TYPE_TERMINOLOGY = "terminology"
DOC_TYPE_ENTITY = "entity"
VALID_DOC_TYPES = frozenset(
    {
        DOC_TYPE_DOC,
        DOC_TYPE_PROCESS,
        DOC_TYPE_CASE,
        DOC_TYPE_QA,
        DOC_TYPE_TERMINOLOGY,
        DOC_TYPE_ENTITY,
    },
)

#: 审核动作（``kb_reviews.action``）：submit→in_review，approve→published，
#: reject→draft，archive→archived（目标状态映射见 wiki.py）
REVIEW_SUBMIT = "submit"
REVIEW_APPROVE = "approve"
REVIEW_REJECT = "reject"
REVIEW_ARCHIVE = "archive"
VALID_REVIEW_ACTIONS = frozenset(
    {REVIEW_SUBMIT, REVIEW_APPROVE, REVIEW_REJECT, REVIEW_ARCHIVE},
)

#: 冲突解决状态（``kb_conflicts.resolution_status``）
CONFLICT_OPEN = "open"
CONFLICT_RESOLVED = "resolved"
VALID_CONFLICT_STATUSES = frozenset(
    {CONFLICT_OPEN, CONFLICT_RESOLVED},
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
    org_id: str = "default"  # org scope: the owning org（租户边界）
    description: str = ""
    # Explicit ACL extension beyond the scope (roles/users/teams).
    grants_roles: List[str] = Field(default_factory=list)
    grants_users: List[str] = Field(default_factory=list)
    grants_teams: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class KbDocumentMeta(BaseModel):
    """One ingested document's registry entry.

    json 面冗余知识生命周期字段（T3）：L0 文件面检索过滤需要状态与有效期，
    而文件面只有 registry 可读——字段缺省 published/无界，存量 JSONL
    反序列化后行为与升级前完全一致（json 面降级语义）。
    """

    doc_id: str
    kb_id: str
    title: str = ""
    source: str = ""
    chunk_count: int = 0
    knowledge_status: str = KNOWLEDGE_PUBLISHED
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("knowledge_status")
    @classmethod
    def _validate_knowledge_status(cls, value: str) -> str:
        # 镜像 ck_kb_documents_knowledge_status（0046）
        return _require_enum_value(
            "knowledge_status",
            VALID_KNOWLEDGE_STATUSES,
            value,
        )


class KbChunk(BaseModel):
    """One retrievable text chunk."""

    chunk_id: str
    kb_id: str
    doc_id: str
    title: str = ""
    seq: int = 0
    text: str
    # S2 expand=section 的结构锚点（切片器 heading_path/parent_seq 随行）。
    # L0/json 面不承载结构字段（file_engine 边界）→ 恒空串/None，S2 自然降级
    # 为单块；pg/milvus 面由 _hit_to_chunk 从 KbSearchHit 回填真值。
    heading_path: str = ""
    parent_seq: Optional[int] = None
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
    # org scope 的归属组织（0044：org 即租户边界，单租户恒为 default）
    org_id: str = "default"
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
    """One knowledge document（``kb_documents`` 行，知识内容的权威源）。

    T3 wiki 化字段（0046）：``knowledge_status`` / ``doc_type`` 有 DB CHECK
    镜像校验；``confidence`` ∈ [0,1]；``valid_from/valid_to`` 为事实有效期
    （NULL=无界）；生命周期写入只走 wiki.py 的审核通道，摄入路径
    （``upsert_document``）不重置这些列。
    """

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
    # --- T3 知识生命周期与分类（0046）---
    knowledge_status: str = KNOWLEDGE_PUBLISHED
    domain: str = ""
    doc_type: str = DOC_TYPE_DOC
    confidence: float = 1.0
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    reviewed_by: str = ""
    review_note: str = ""
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

    @field_validator("knowledge_status")
    @classmethod
    def _validate_knowledge_status(cls, value: str) -> str:
        # 镜像 ck_kb_documents_knowledge_status（0046）
        return _require_enum_value(
            "knowledge_status",
            VALID_KNOWLEDGE_STATUSES,
            value,
        )

    @field_validator("doc_type")
    @classmethod
    def _validate_doc_type(cls, value: str) -> str:
        # 镜像 ck_kb_documents_doc_type（0046）
        return _require_enum_value("doc_type", VALID_DOC_TYPES, value)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        # 置信度是检索排序与冲突优先级的输入，出界的值会让下游比较失真
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence 取值须在 [0, 1] 之内")
        return value


#: 绑定主体类型常量（T6 泛化，0048 ``principal_type`` 列的合法取值）。
#: team 行的 ``agent_id`` 列存 ``expert_teams.id`` 的运行态形态
#: ``team_{team_id}``（``expert_team_agent_id`` 惯例），列名不改保兼容。
PRINCIPAL_AGENT = "agent"
PRINCIPAL_TEAM = "team"


class KbBinding(BaseModel):
    """One agent↔space authorization binding（``agent_kb_bindings`` 行）。

    绑定即授权（spec 决策点 1）：非空行表示该数字员工可在检索时收敛
    到该库（S0 ACL 交集来源）；写入前须经 ``can_manage_space`` 管理权校验。
    """

    agent_id: str
    space_id: str
    #: 绑定主体类型（T6 泛化）：agent-数字员工直绑（存量语义，默认）/
    #: team-专家组绑（agent_id 列存 ``team_{team_id}`` 运行态形态）。
    principal_type: str = PRINCIPAL_AGENT
    granted_by: str = ""
    remark: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class KbDocumentVersion(BaseModel):
    """One document version snapshot（``kb_document_versions`` 行）。"""

    document_id: str
    version: int
    content_md: str = ""
    content_hash: str = ""
    created_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class KbReview(BaseModel):
    """One lifecycle review record（``kb_reviews`` 行，0046 审核流水）。"""

    id: str
    space_id: str
    document_id: str
    action: str = REVIEW_SUBMIT
    reviewer: str = ""
    comment: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        # 镜像 ck_kb_reviews_action（0046）
        return _require_enum_value("action", VALID_REVIEW_ACTIONS, value)


class KbConflict(BaseModel):
    """One knowledge conflict candidate（``kb_conflicts`` 行，0046）。"""

    id: str
    space_id: str
    document_id_a: str
    document_id_b: str
    # 规则判定产物：duplicate_title（同库同名）；LLM 辅助判定为后续增强
    conflict_type: str = "duplicate_title"
    affected_scope: str = ""
    # 1~5，5 最高（当前按双文档 confidence 最低值归档，wiki.py）
    priority: int = 3
    resolution_status: str = CONFLICT_OPEN
    resolved_by: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("resolution_status")
    @classmethod
    def _validate_resolution_status(cls, value: str) -> str:
        # 镜像 ck_kb_conflicts_resolution_status（0046）
        return _require_enum_value(
            "resolution_status",
            VALID_CONFLICT_STATUSES,
            value,
        )
