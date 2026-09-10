# -*- coding: utf-8 -*-
"""Agent document revision snapshots (Phase B publish chain).

Revision ID: 0022_agent_document_revisions
Revises: 0021_agent_model_slot_overrides
Create Date: 2026-09-10

Adds ``agent_document_revisions``: immutable per-publish snapshots of the
authoritative ``agent_documents`` rows. Every promote (publish / rollback)
that changes a document inserts a snapshot with the row's new version;
retention keeps the most recent 20 per document (psql twin: changelog
20260910/02).

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0022_agent_document_revisions"
down_revision = "0021_agent_model_slot_overrides"
branch_labels = None
depends_on = None

_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS agent_document_revisions (
        tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
        id           BIGSERIAL PRIMARY KEY,
        agent_id     VARCHAR(64) NOT NULL,
        doc_type     VARCHAR(32) NOT NULL,
        environment  VARCHAR(16) NOT NULL DEFAULT 'production',
        version      INTEGER NOT NULL,
        content      TEXT NOT NULL DEFAULT '',
        content_hash VARCHAR(64) NOT NULL DEFAULT '',
        published_by TEXT,
        published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_agent_document_revisions_version
            UNIQUE (tenant_id, agent_id, doc_type, environment, version),
        CONSTRAINT ck_agent_document_revisions_doc_type
            CHECK (doc_type IN ('profile', 'agents', 'soul', 'agent_json')),
        CONSTRAINT ck_agent_document_revisions_environment
            CHECK (environment IN ('draft', 'production'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agent_document_revisions_doc "
    "ON agent_document_revisions (tenant_id, agent_id, doc_type)",
)

_COMMENTS = (
    "COMMENT ON TABLE agent_document_revisions IS "
    "'数字员工档案文档版本快照表：发布/回滚每次变更 production 行时插入不可变快照，"
    "每文档惰性保留最近 20 版'",
    "COMMENT ON COLUMN agent_document_revisions.agent_id IS "
    "'智能体标识（工作区目录名，与 AgentProfileRef.id 一致）'",
    "COMMENT ON COLUMN agent_document_revisions.doc_type IS "
    "'文档类型: profile-PROFILE.md, agents-AGENTS.md, soul-SOUL.md, "
    "agent_json-agent.json'",
    "COMMENT ON COLUMN agent_document_revisions.environment IS "
    "'环境: draft-调试草稿, production-线上发布'",
    "COMMENT ON COLUMN agent_document_revisions.version IS "
    "'快照对应的生产行版本号（与 agent_documents.version 同源）'",
    "COMMENT ON COLUMN agent_document_revisions.content IS '快照文档全文内容'",
    "COMMENT ON COLUMN agent_document_revisions.content_hash IS "
    "'内容 SHA-256 摘要'",
    "COMMENT ON COLUMN agent_document_revisions.published_by IS "
    "'发布/回滚操作人标识'",
    "COMMENT ON COLUMN agent_document_revisions.published_at IS "
    "'快照时间（DB 自动维护，UTC）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260910/02 的等价 alembic 路径）
    for ddl in _DDLS:
        op.execute(ddl)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_document_revisions")
