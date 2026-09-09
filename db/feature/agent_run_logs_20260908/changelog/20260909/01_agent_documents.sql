-- [变更说明] 新增数字员工档案文档表 agent_documents（PROFILE/AGENTS/SOUL/agent.json 的 PG 权威存储，Phase A 影子双写）
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- ============================================================
-- agent_documents：数字员工档案文档表
-- alembic 等价路径：0014_agent_documents
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_documents (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    id           BIGSERIAL PRIMARY KEY,
    agent_id     VARCHAR(64) NOT NULL,
    doc_type     VARCHAR(32) NOT NULL,
    environment  VARCHAR(16) NOT NULL DEFAULT 'production',
    content      TEXT NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    version      INTEGER NOT NULL DEFAULT 1,
    updated_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_documents_doc
        UNIQUE (tenant_id, agent_id, doc_type, environment),
    CONSTRAINT ck_agent_documents_doc_type
        CHECK (doc_type IN ('profile', 'agents', 'soul', 'agent_json')),
    CONSTRAINT ck_agent_documents_environment
        CHECK (environment IN ('draft', 'production'))
);

CREATE INDEX IF NOT EXISTS idx_agent_documents_agent
    ON agent_documents (tenant_id, agent_id);

COMMENT ON TABLE agent_documents IS '数字员工档案文档表：PROFILE/AGENTS/SOUL/agent.json 的 PG 权威存储（Phase A 影子双写，Phase B 读切换；environment 区分草稿/生产）';

COMMENT ON COLUMN agent_documents.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN agent_documents.id IS '文档行 ID（BIGSERIAL 自增主键）';

COMMENT ON COLUMN agent_documents.agent_id IS '智能体标识（工作区目录名，与 AgentProfileRef.id 一致）';

COMMENT ON COLUMN agent_documents.doc_type IS '文档类型: profile-PROFILE.md, agents-AGENTS.md, soul-SOUL.md, agent_json-agent.json';

COMMENT ON COLUMN agent_documents.environment IS '环境: draft-调试草稿, production-线上发布';

COMMENT ON COLUMN agent_documents.content IS '文档全文内容';

COMMENT ON COLUMN agent_documents.content_hash IS '内容 SHA-256 摘要（幂等 upsert 判据，内容未变时不递增版本）';

COMMENT ON COLUMN agent_documents.version IS '文档版本号，内容变更时单调递增';

COMMENT ON COLUMN agent_documents.updated_by IS '最后修改人标识';

COMMENT ON COLUMN agent_documents.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN agent_documents.updated_at IS '更新时间（DB 自动维护，UTC）';
