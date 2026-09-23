-- [变更说明] 新增 MCP/ACP 驱动卡 PG 权威双表（T12 driver PG 权威）：
--            1) driver_cards：数字员工外部能力驱动卡（MCP/ACP）权威表，
--               自然键 (tenant, agent, protocol, name)；enabled 独立列，
--               spec JSONB 承载 endpoint/config/credentials(alias→{kind,ref})，
--               policy JSONB 承载 DriverPolicy（默认效应 + 规则数组）；
--            2) driver_credentials：驱动凭据密文表，自然键
--               (tenant, agent, ref)；cipher 存放经 secret_store（Fernet）
--               加密后的凭据 JSON（kind/public/secrets/meta），明文不落库。
--            json 后端（无 PG）两表零动作，驱动卡仍走 workspace 文件平面；
--            pg/dual 后端以本两表为权威源，文件降级为投影（写穿 + 启动回填）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0039_driver_cards_credentials
--
-- 全部 DDL 幂等（CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS）。

CREATE TABLE IF NOT EXISTS driver_cards (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    protocol VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    spec JSONB NOT NULL DEFAULT '{}',
    policy JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_cards
        PRIMARY KEY (tenant_id, agent_id, protocol, name)
);

CREATE INDEX IF NOT EXISTS ix_driver_cards_agent
    ON driver_cards (tenant_id, agent_id);

CREATE TABLE IF NOT EXISTS driver_credentials (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    cipher TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_credentials
        PRIMARY KEY (tenant_id, agent_id, ref)
);

CREATE INDEX IF NOT EXISTS ix_driver_credentials_agent
    ON driver_credentials (tenant_id, agent_id);

COMMENT ON TABLE driver_cards IS
    'MCP/ACP 驱动卡权威表（数字员工外部能力配置：endpoint/config/凭据引用/访问策略；json 后端零动作、pg/dual 权威，文件降级为写穿投影 + 启动回填）';
COMMENT ON COLUMN driver_cards.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN driver_cards.agent_id IS '数字员工 ID（workspace 目录名，与 agent_documents 同约定）';
COMMENT ON COLUMN driver_cards.protocol IS '驱动协议（如 mcp/acp，与文件投影目录 drivers/{protocol}/{name}.yaml 对齐）';
COMMENT ON COLUMN driver_cards.name IS '驱动卡名（同 agent+protocol 内唯一，运行时全局唯一）';
COMMENT ON COLUMN driver_cards.enabled IS '是否启用（禁用后运行时不构建该 driver）';
COMMENT ON COLUMN driver_cards.spec IS '驱动卡主体 JSONB（endpoint/config/credentials：alias→{kind,ref}；凭据密文另存 driver_credentials）';
COMMENT ON COLUMN driver_cards.policy IS '访问策略 JSONB（DriverPolicy：default_effect + rules 数组）';
COMMENT ON COLUMN driver_cards.created_at IS '创建时间（首次写入时生成）';
COMMENT ON COLUMN driver_cards.updated_at IS '更新时间（每次内容变更时刷新）';

COMMENT ON TABLE driver_credentials IS
    '驱动凭据密文表（secret_store/Fernet 加密后的凭据 JSON：kind/public/secrets/meta；明文绝不落库，cipher 为空表示无密文）';
COMMENT ON COLUMN driver_credentials.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN driver_credentials.agent_id IS '数字员工 ID（workspace 目录名）';
COMMENT ON COLUMN driver_credentials.ref IS '凭据引用（与 DriverCard.credentials 的 ref 对应，env: 前缀引用不落库）';
COMMENT ON COLUMN driver_credentials.cipher IS '凭据密文（secret_store.encrypt 后的 JSON，带 ENC: 前缀；读取时 decrypt 还原）';
COMMENT ON COLUMN driver_credentials.created_at IS '创建时间（首次写入时生成）';
COMMENT ON COLUMN driver_credentials.updated_at IS '更新时间（每次内容变更时刷新）';
