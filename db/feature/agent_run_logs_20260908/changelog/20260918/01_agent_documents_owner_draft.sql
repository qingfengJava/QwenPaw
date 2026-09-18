-- [变更说明] agent_documents 增加 owner_user_id 个人草稿维（T11 个人档案草稿）：
--            1) 加列 owner_user_id（NULL=员工共享行；非空=该用户的个人草稿行，
--               与正式 agent_id 的 environment=draft 组合承载「员工写四文档
--               落本人 draft 行（不触共享行）」）；
--            2) 唯一约束重建：旧约束 uq_agent_documents_doc
--               (tenant,agent,doc_type,environment) 删除，改为表达式唯一索引
--               （owner NULL 归一为空串）——允许同一文档下多用户各持一份
--               个人草稿，同时保持共享行唯一；
--            3) 存量行 owner_user_id 为 NULL，语义不变（共享行）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0038_agent_documents_owner_draft
--
-- 全部 DDL 幂等（ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS /
-- CREATE UNIQUE INDEX IF NOT EXISTS）。

ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64);

ALTER TABLE agent_documents DROP CONSTRAINT IF EXISTS uq_agent_documents_doc;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_documents_doc_owner
    ON agent_documents (tenant_id, agent_id, doc_type, environment,
                        COALESCE(owner_user_id, ''));

COMMENT ON COLUMN agent_documents.owner_user_id IS
    '个人草稿 owner（NULL=员工共享行；非空=该用户的个人草稿行，与 environment=draft 组合；管理员应用 apply 后 promote 到共享行）';