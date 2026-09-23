# -*- coding: utf-8 -*-
"""KB wiki plane: document lifecycle + reviews + conflicts (ontology T3).

Revision ID: 0046_kb_wiki
Revises: 0045_kb_chunk_meta
Create Date: 2026-09-20

知识本体平台 T3（LLM Wiki 知识层，治理闭环）：

- ``kb_documents`` wiki 化列（与 ``ingest_status`` 正交——ingest 答
  「索引就绪吗」，knowledge 答「内容可信可检吗」）：
  ``knowledge_status``（draft/in_review/published/archived，存量回填
  ``published`` 语义 = 现行即时生效）、``domain``、``doc_type``、
  ``confidence``、``valid_from``/``valid_to``、``reviewed_by``、
  ``review_note``；
- ``kb_reviews``：生命周期审核流水（submit/approve/reject/archive）；
- ``kb_conflicts``：知识冲突候选（规则判定 duplicate_title 起步）；
- ``ix_kb_documents_status``：按库 + 状态过滤文档清单的覆盖索引。

检索默认只出 ``published`` 且在有效期内（pg_engine SQL JOIN 过滤，
T3 落地）。全部 DDL 幂等。（psql twin: changelog 20260920/04）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0046_kb_wiki"
down_revision = "0045_kb_chunk_meta"
branch_labels = None
depends_on = None

_ADD_COLUMNS = (
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS knowledge_status "
    "VARCHAR(20) NOT NULL DEFAULT 'published'",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS domain "
    "VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS doc_type "
    "VARCHAR(32) NOT NULL DEFAULT 'doc'",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS confidence "
    "REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS reviewed_by "
    "VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS review_note "
    "TEXT NOT NULL DEFAULT ''",
)

_CREATE_REVIEWS = """
CREATE TABLE IF NOT EXISTS kb_reviews (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    document_id VARCHAR(64) NOT NULL,
    action VARCHAR(20) NOT NULL,
    reviewer VARCHAR(64) NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
)
"""

_CREATE_CONFLICTS = """
CREATE TABLE IF NOT EXISTS kb_conflicts (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    document_id_a VARCHAR(64) NOT NULL,
    document_id_b VARCHAR(64) NOT NULL,
    conflict_type VARCHAR(32) NOT NULL DEFAULT 'duplicate_title',
    affected_scope VARCHAR(128) NOT NULL DEFAULT '',
    priority INT NOT NULL DEFAULT 3,
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolved_by VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
)
"""

_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_kb_documents_status "
    "ON kb_documents (tenant_id, space_id, knowledge_status)",
)

_COMMENTS = (
    "COMMENT ON COLUMN kb_documents.knowledge_status IS "
    "'知识生命周期: draft-草稿, in_review-待审, published-已发布(可检), "
    "archived-已归档；与 ingest_status 正交，检索默认只出 published'",
    "COMMENT ON COLUMN kb_documents.domain IS "
    "'知识域（六大域建议值：企业基础/业务域/流程SOP/专业知识/案例/QA，自由文本不硬约束）'",
    "COMMENT ON COLUMN kb_documents.doc_type IS "
    "'文档类型: doc-文档, process-流程, case-案例, qa-问答, "
    "terminology-术语, entity-实体卡'",
    "COMMENT ON COLUMN kb_documents.confidence IS "
    "'内容置信度 [0,1]；冲突优先级与排序的输入，LLM 建议经人工确认后落库'",
    "COMMENT ON COLUMN kb_documents.valid_from IS "
    "'事实有效期起（NULL=无界；检索过滤条件之一）'",
    "COMMENT ON COLUMN kb_documents.valid_to IS "
    "'事实有效期止（NULL=无界；过期文档默认不可检）'",
    "COMMENT ON COLUMN kb_documents.reviewed_by IS "
    "'最近一次 approve 的审核人（reject/archive 记 review_note 不改本列）'",
    "COMMENT ON COLUMN kb_documents.review_note IS "
    "'最近一次审核备注（reject 理由/归档说明）'",
    "COMMENT ON TABLE kb_reviews IS "
    "'知识生命周期审核流水（每次 submit/approve/reject/archive 追加一条）'",
    "COMMENT ON TABLE kb_conflicts IS "
    "'知识冲突候选（规则判定 duplicate_title 起步；resolve 后保留流水）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    op.execute(_CREATE_REVIEWS)
    op.execute(_CREATE_CONFLICTS)
    for statement in _CREATE_INDEX:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_documents_status")
    op.execute("DROP TABLE IF EXISTS kb_conflicts")
    op.execute("DROP TABLE IF EXISTS kb_reviews")
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS review_note",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS reviewed_by",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS valid_to",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS valid_from",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS confidence",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS doc_type",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS domain",
    )
    op.execute(
        "ALTER TABLE kb_documents DROP COLUMN IF EXISTS knowledge_status",
    )
