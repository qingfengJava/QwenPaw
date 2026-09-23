-- [变更说明] 模型提供商配置落库平面：新增 provider_configs（整包快照 JSONB + api_key ENC: 密文提升列）与 model_active_slots（active_llm 槽位）
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [说明]     QWENPAW_STORAGE_BACKEND=json（默认）时两表不参与读写路径；
--            api_key 仅以 ENC: 密文入库，绝无明文数据随本文件上传。

-- 模型提供商配置表（api_key 密文提升列 + 整包快照 JSONB）
CREATE TABLE IF NOT EXISTS provider_configs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    api_key_encrypted TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot JSONB NOT NULL DEFAULT '{}',
    snapshot_schema_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_configs PRIMARY KEY (tenant_id, provider_id)
);

-- 模型槽位表（承接 active_llm；slot_name 现阶段固定 llm）
CREATE TABLE IF NOT EXISTS model_active_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    slot_name VARCHAR(32) NOT NULL,
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_model_active_slots PRIMARY KEY (tenant_id, slot_name)
);

COMMENT ON TABLE provider_configs IS
'模型提供商配置落库平面（api_key 以 ENC: 密文存储，snapshot 为整包 provider 快照 JSONB）';
COMMENT ON COLUMN provider_configs.api_key_encrypted IS
'Fernet 加密后的 API Key（ENC: 前缀，主密钥见 secret_store）';
COMMENT ON COLUMN provider_configs.enabled IS
'厂商启用状态（镜像控制台语义：需要 key 且未配置即停用）';
COMMENT ON COLUMN provider_configs.snapshot IS
'整包 provider 快照（extra_models/discovered_models/hidden_model_ids/removed_model_ids 等，不含 api_key 明文）';
COMMENT ON TABLE model_active_slots IS
'模型槽位表（承接 active_llm；slot_name 现阶段固定 llm）';
COMMENT ON COLUMN model_active_slots.slot_name IS
'槽位名: llm（预留 embedding 等）';
