-- ============================================================
-- 变更说明: 知识本体平台 T1 —— kb_spaces 增 org_id 列 + scope CHECK
--           枚举扩 'org'（四级权限 personal/team/org/enterprise）。
--           1) org_id：org scope 的归属组织（org 即租户边界，与
--              orgs.id 同域；单租户部署恒为 default）；
--           2) ck_kb_spaces_scope 约束换血（幂等 DO 块）；
--           3) ix_kb_spaces_org 覆盖索引。
--           模型侧 KnowledgeBase/KbSpace 已带 org_id（默认 default），
--           json 平面无 DDL、语义同批生效。
-- 变更时间: 2026-09-20
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0044_kb_org_scope（Revises 0043_employee_profile）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

ALTER TABLE kb_spaces
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(64) NOT NULL DEFAULT 'default';

DO $$
BEGIN
    ALTER TABLE kb_spaces
        DROP CONSTRAINT IF EXISTS ck_kb_spaces_scope;
    ALTER TABLE kb_spaces
        ADD CONSTRAINT ck_kb_spaces_scope
        CHECK (scope IN ('personal', 'team', 'org', 'enterprise'));
END
$$;

CREATE INDEX IF NOT EXISTS ix_kb_spaces_org
    ON kb_spaces (tenant_id, org_id);

COMMENT ON COLUMN kb_spaces.org_id IS
    'org scope 的归属组织 id（org 即租户边界，与 orgs.id 同域；'
    '单租户部署恒为 default；org 库对组织内全部认证成员可读）';

-- 验证（手工执行）：
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--  WHERE conrelid = 'kb_spaces'::regclass AND conname = 'ck_kb_spaces_scope';
-- SELECT column_name, data_type, column_default FROM information_schema.columns
--  WHERE table_name = 'kb_spaces' AND column_name = 'org_id';
