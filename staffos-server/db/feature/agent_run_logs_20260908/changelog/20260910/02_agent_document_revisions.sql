-- [变更说明] 数字员工档案文档版本快照表 agent_document_revisions：发布/回滚每次变更 production 权威行时插入不可变版本快照（content/content_hash/published_by），每文档惰性保留最近 20 版，支撑档案历史查看与一键回滚（Phase B 发布闭环）
-- [变更时间] 2026-09-10
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- ============================================================
-- agent_document_revisions：档案文档版本快照表
-- alembic 等价路径：0022_agent_document_revisions
-- ============================================================

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
);

CREATE INDEX IF NOT EXISTS idx_agent_document_revisions_doc
    ON agent_document_revisions (tenant_id, agent_id, doc_type);

COMMENT ON TABLE agent_document_revisions IS '数字员工档案文档版本快照表：发布/回滚每次变更 production 行时插入不可变快照，每文档惰性保留最近 20 版';

COMMENT ON COLUMN agent_document_revisions.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN agent_document_revisions.id IS '快照行 ID（BIGSERIAL 自增主键）';

COMMENT ON COLUMN agent_document_revisions.agent_id IS '智能体标识（工作区目录名，与 AgentProfileRef.id 一致）';

COMMENT ON COLUMN agent_document_revisions.doc_type IS '文档类型: profile-PROFILE.md, agents-AGENTS.md, soul-SOUL.md, agent_json-agent.json';

COMMENT ON COLUMN agent_document_revisions.environment IS '环境: draft-调试草稿, production-线上发布';

COMMENT ON COLUMN agent_document_revisions.version IS '快照对应的生产行版本号（与 agent_documents.version 同源）';

COMMENT ON COLUMN agent_document_revisions.content IS '快照文档全文内容';

COMMENT ON COLUMN agent_document_revisions.content_hash IS '内容 SHA-256 摘要';

COMMENT ON COLUMN agent_document_revisions.published_by IS '发布/回滚操作人标识';

COMMENT ON COLUMN agent_document_revisions.published_at IS '快照时间（DB 自动维护，UTC）';
