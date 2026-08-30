-- ============================================================
-- 变更说明: 员工级开放 API 密钥（P4 /api/open 的凭证面）——
--           新表 expert_api_keys：数字员工 API Key 的签发/吊销台账。
--           明文密钥（sk_ek_<random>）仅在签发响应中返回一次，落库
--           只存 SHA-256 哈希 + 前缀（展示用）；expert_id 即权限边界
--           （该 key 只能访问对应员工）；revoked_at 软吊销留痕。
-- 变更时间: 2026-08-30
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0013_expert_api_keys（Revises 0012_digital_employee_capability）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS expert_api_keys (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    expert_id   VARCHAR(64) NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    key_hash    TEXT NOT NULL,
    key_prefix  TEXT NOT NULL DEFAULT '',
    created_by  TEXT,
    expires_at  TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_api_keys PRIMARY KEY (tenant_id, id),
    CONSTRAINT uq_expert_api_keys_hash UNIQUE (tenant_id, key_hash)
);

COMMENT ON TABLE expert_api_keys IS '员工级开放 API 密钥台账（P4）：明文仅签发时返回一次，落库为 SHA-256 哈希；expert_id 即权限边界；revoked_at 非空 = 已吊销';
COMMENT ON COLUMN expert_api_keys.key_hash IS '密钥的 SHA-256 十六进制哈希（永不存明文）';
COMMENT ON COLUMN expert_api_keys.key_prefix IS '密钥前缀（sk_ek_ 前 12 字符，列表展示/辨识用）';
COMMENT ON COLUMN expert_api_keys.revoked_at IS '吊销时间（NULL=有效）';

CREATE INDEX IF NOT EXISTS idx_expert_api_keys_expert
    ON expert_api_keys (tenant_id, expert_id);

-- ------------------------------------------------------------
-- Alembic 版本标记推进（0012 → 0013）
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0013_expert_api_keys';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0013_expert_api_keys');
    END IF;
END $$;

COMMIT;
