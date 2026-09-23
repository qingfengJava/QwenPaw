-- [变更说明] 供应商模型行级表 provider_models：每厂商每模型一行，参数独立（config JSONB + 能力提升列），由 provider_configs.snapshot 每次变更自动投影同步
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [说明]     provider_configs.snapshot 仍是内存重建权威；本表为规范化投影，
--            供人工查询/BI/未来行级关联（如数字员工模型绑定）使用。

CREATE TABLE IF NOT EXISTS provider_models (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    model_id VARCHAR(128) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    source VARCHAR(16) NOT NULL DEFAULT 'builtin',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_free BOOLEAN NOT NULL DEFAULT FALSE,
    supports_multimodal BOOLEAN,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_models
        PRIMARY KEY (tenant_id, provider_id, model_id)
);

COMMENT ON TABLE provider_models IS
'供应商模型行级表（每厂商每模型一行，参数独立；由 provider_configs.snapshot 每次变更自动投影同步）';
COMMENT ON COLUMN provider_models.model_id IS
'模型 ID（如 qwen3.7-max）';
COMMENT ON COLUMN provider_models.source IS
'模型来源: builtin(内置目录), user(用户添加), discovered(自动发现)';
COMMENT ON COLUMN provider_models.enabled IS
'启用开关（false=已禁用：保留配置但从所有选择器隐藏）';
COMMENT ON COLUMN provider_models.config IS
'模型级参数（generate_kwargs/config_overrides/thinking/max_input_length 等全部其余字段）';
