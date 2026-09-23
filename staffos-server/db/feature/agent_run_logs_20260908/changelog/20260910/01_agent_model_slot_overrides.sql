-- [变更说明] agent_model_slots 模型参数档案化：加 config JSONB（模型参数覆盖，NULL=跟随全局基线）+ 主键扩展到模型维度（一行=员工×模型参数档案）+ is_active 激活位与唯一激活索引（切换模型即切换激活档案，切回自动恢复历史参数）
-- [变更时间] 2026-09-10
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- ============================================================
-- agent_model_slots 档案化
-- alembic 等价路径：0021_agent_model_slot_overrides（修订版）
-- 注意：以下语句逐条执行（asyncpg 不支持多语句批量）
-- ============================================================

ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS config JSONB;

COMMENT ON COLUMN agent_model_slots.config IS
'模型参数档案 JSONB（max_input_length/thinking_enabled/thinking_budget/reasoning_effort；NULL 或字段缺省=跟随全局基线；归属该行的 provider_id+model）';

ALTER TABLE agent_model_slots
    DROP CONSTRAINT IF EXISTS pk_agent_model_slots;

ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE agent_model_slots SET is_active = TRUE WHERE NOT is_active;

ALTER TABLE agent_model_slots
    ADD CONSTRAINT pk_agent_model_slots
    PRIMARY KEY (tenant_id, agent_id, slot_name, provider_id, model);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_model_slots_active
    ON agent_model_slots (tenant_id, agent_id, slot_name) WHERE is_active;

COMMENT ON COLUMN agent_model_slots.is_active IS
'激活状态位：当前生效的模型档案；同一员工同一槽位至多一行 TRUE';
