-- [变更说明] 数字员工默认模型槽位表：新增 agent_model_slots（后台为每个数字员工配置的默认运行模型，PG 权威/影子随 QWENPAW_STORAGE_BACKEND 三态切换）
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [说明]     列结构与 model_active_slots 完全对齐并增加 agent_id 维度；
--            json（默认）后端不参与任何读写路径，dual 影子双写，pg 权威读；
--            运行时解析优先级：本表 → agent.json active_model → 全局 active_llm。
--            alembic 等价路径：0020_agent_model_slots。

-- 数字员工默认模型槽位表（每员工每槽位一行，slot_name 现阶段固定 llm）
CREATE TABLE IF NOT EXISTS agent_model_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    slot_name VARCHAR(32) NOT NULL DEFAULT 'llm',
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_model_slots PRIMARY KEY (tenant_id, agent_id, slot_name)
);

COMMENT ON TABLE agent_model_slots IS
'数字员工默认模型槽位表（后台档案区为每个员工配置的默认运行模型；agent.json active_model 的 PG 落库平面，运行时解析优先级：本表 → agent.json → 全局 active_llm）';
COMMENT ON COLUMN agent_model_slots.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN agent_model_slots.agent_id IS
'数字员工 ID（智能体档案 ID，如 python-fullstack）';
COMMENT ON COLUMN agent_model_slots.slot_name IS
'槽位名: llm（预留 embedding 等槽位）';
COMMENT ON COLUMN agent_model_slots.provider_id IS
'模型提供商 ID（如 aliyun-codingplan；空串视为未配置，解析时跳过本表回退 agent.json）';
COMMENT ON COLUMN agent_model_slots.model IS
'模型 ID（如 GLM-5.3-Flash；空串视为未配置）';
COMMENT ON COLUMN agent_model_slots.created_at IS
'创建时间（首次配置默认模型时写入）';
COMMENT ON COLUMN agent_model_slots.updated_at IS
'更新时间（每次切换默认模型时刷新）';
