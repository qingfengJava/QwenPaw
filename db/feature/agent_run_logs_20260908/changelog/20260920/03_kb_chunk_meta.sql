-- ============================================================
-- 变更说明: 知识本体平台 T2 —— kb_chunks 增本体挂接元数据 4 列
--           （Evidence 层证据元数据预留，迁移先行、写入后接）：
--           1) knowledge_id：切片归属的本体知识节点 id（T4 回填）；
--           2) entity_ids：切片提及的实体 id 数组（JSONB，T4 抽取）；
--           3) valid_from / valid_to：事实有效期（时效过滤/降权用）。
--           全部 NULL-able 纯加列，存量行语义不变；索引待 T5 编排器
--           定稿查询形态后再建。
-- 变更时间: 2026-09-20
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0045_kb_chunk_meta（Revises 0044_kb_org_scope）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS knowledge_id VARCHAR(64);

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS entity_ids JSONB;

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;

COMMENT ON COLUMN kb_chunks.knowledge_id IS
    '切片归属的本体知识节点 id（T4 摄入回填；NULL=未挂接本体）';

COMMENT ON COLUMN kb_chunks.entity_ids IS
    '切片提及的实体 id 数组（JSONB；T4 抽取回填，编排器过滤/扩展用）';

COMMENT ON COLUMN kb_chunks.valid_from IS
    '事实有效期起（NULL=无时效约束；时效过滤与过期降权用）';

COMMENT ON COLUMN kb_chunks.valid_to IS
    '事实有效期止（NULL=无时效约束；时效过滤与过期降权用）';

-- 验证（手工执行）：
-- SELECT column_name, data_type, is_nullable
--  FROM information_schema.columns
--  WHERE table_name = 'kb_chunks'
--    AND column_name IN ('knowledge_id', 'entity_ids',
--                        'valid_from', 'valid_to')
--  ORDER BY column_name;
