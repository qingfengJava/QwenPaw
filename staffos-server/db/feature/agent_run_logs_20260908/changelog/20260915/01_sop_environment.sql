-- [变更说明] SOP 环境隔离（draft/production 双行 + promote）：
--            1) sops 增列 environment（draft-调试草稿 / production-线上发布），
--               默认 production，存量行天然落到线上环境；
--            2) 主键由 (tenant_id, id) 重建为 (tenant_id, id, environment)，
--               允许同一 SOP 在草稿与线上各存一行，互不污染；
--            3) sop_versions 版本链保持不变（仅跟 production 行）。
--            对齐 agent_documents 的 draft/production 双行 + promote 语义。
-- [变更时间] 2026-09-15
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0030_sop_environment

-- 幂等加列：存量库补列 / 新库 CREATE TABLE 后补齐，双路径安全
ALTER TABLE sops ADD COLUMN IF NOT EXISTS
    environment VARCHAR(16) NOT NULL DEFAULT 'production';

-- CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sops_environment'
    ) THEN
        ALTER TABLE sops ADD CONSTRAINT
        ck_sops_environment
        CHECK (environment IN ('draft', 'production'));
    END IF;
END
$$;

-- 主键重建：先删旧 (tenant_id, id)，再建新 (tenant_id, id, environment)
ALTER TABLE sops DROP CONSTRAINT IF EXISTS pk_sops;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pk_sops'
    ) THEN
        ALTER TABLE sops ADD CONSTRAINT pk_sops
        PRIMARY KEY (tenant_id, id, environment);
    END IF;
END
$$;

-- 环境维度下的常用查询索引（按归属员工 + 环境过滤草稿/线上列表）
CREATE INDEX IF NOT EXISTS idx_sops_owner_env
    ON sops (tenant_id, owner_id, environment);

COMMENT ON COLUMN sops.environment IS
    '环境: draft-调试草稿(工作台编辑), production-线上发布(运行时注入)；'
    '同一 SOP 两环境各存一行，promote 时草稿覆盖线上并写版本快照';
