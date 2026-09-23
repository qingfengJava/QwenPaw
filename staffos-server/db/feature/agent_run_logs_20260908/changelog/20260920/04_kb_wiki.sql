-- ============================================================
-- 变更说明: 知识本体平台 T3 —— LLM Wiki 知识层（治理闭环）：
--           1) kb_documents wiki 化 8 列：knowledge_status（draft/
--              in_review/published/archived，存量回填 published 语义=
--              现行即时生效）/ domain / doc_type / confidence /
--              valid_from / valid_to / reviewed_by / review_note；
--           2) kb_reviews 审核流水表（submit/approve/reject/archive）；
--           3) kb_conflicts 冲突候选表（规则判定 duplicate_title 起步）；
--           4) ix_kb_documents_status 覆盖索引。
--           检索默认只出 published 且在有效期内（pg_engine JOIN 过滤）。
-- 变更时间: 2026-09-20
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0046_kb_wiki（Revises 0045_kb_chunk_meta）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS knowledge_status
    VARCHAR(20) NOT NULL DEFAULT 'published';

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS domain
    VARCHAR(64) NOT NULL DEFAULT '';

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS doc_type
    VARCHAR(32) NOT NULL DEFAULT 'doc';

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS confidence
    REAL NOT NULL DEFAULT 1.0;

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS reviewed_by
    VARCHAR(64) NOT NULL DEFAULT '';

ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS review_note
    TEXT NOT NULL DEFAULT '';

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
);

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
);

CREATE INDEX IF NOT EXISTS ix_kb_documents_status
    ON kb_documents (tenant_id, space_id, knowledge_status);

COMMENT ON COLUMN kb_documents.knowledge_status IS
    '知识生命周期: draft-草稿, in_review-待审, published-已发布(可检), archived-已归档；与 ingest_status 正交，检索默认只出 published';

COMMENT ON COLUMN kb_documents.domain IS
    '知识域（六大域建议值：企业基础/业务域/流程SOP/专业知识/案例/QA，自由文本不硬约束）';

COMMENT ON COLUMN kb_documents.doc_type IS
    '文档类型: doc-文档, process-流程, case-案例, qa-问答, terminology-术语, entity-实体卡';

COMMENT ON COLUMN kb_documents.confidence IS
    '内容置信度 [0,1]；冲突优先级与排序的输入，LLM 建议经人工确认后落库';

COMMENT ON COLUMN kb_documents.valid_from IS
    '事实有效期起（NULL=无界；检索过滤条件之一）';

COMMENT ON COLUMN kb_documents.valid_to IS
    '事实有效期止（NULL=无界；过期文档默认不可检）';

COMMENT ON COLUMN kb_documents.reviewed_by IS
    '最近一次 approve 的审核人（reject/archive 记 review_note 不改本列）';

COMMENT ON COLUMN kb_documents.review_note IS
    '最近一次审核备注（reject 理由/归档说明）';

COMMENT ON TABLE kb_reviews IS
    '知识生命周期审核流水（每次 submit/approve/reject/archive 追加一条）';

COMMENT ON TABLE kb_conflicts IS
    '知识冲突候选（规则判定 duplicate_title 起步；resolve 后保留流水）';

-- 验证（手工执行）：
-- SELECT column_name, data_type, is_nullable, column_default
--  FROM information_schema.columns
--  WHERE table_name = 'kb_documents' AND column_name IN
--    ('knowledge_status','domain','doc_type','confidence',
--     'valid_from','valid_to','reviewed_by','review_note');
-- SELECT to_regclass('public.kb_reviews') AS reviews,
--        to_regclass('public.kb_conflicts') AS conflicts;
