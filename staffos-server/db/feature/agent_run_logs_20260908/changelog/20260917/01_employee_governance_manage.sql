-- [变更说明] 员工治理表增加后台配置域授权三列（manage_visibility /
--            manage_granted_departments / manage_granted_users）：
--            1) manage_visibility 两级：private-仅创建者可配（默认，最严出厂）/
--               department-部门可配（归属 ∪ 管理授权部门）；不支持 org
--               （"全员可配"用 team_lead 角色表达，避免误配）；
--            2) manage_granted_users 显式授权用户名单（全员可配场景的兜底表达）；
--            3) 治理写入由服务层投影到 RBAC agent_manage_grants（S1 共享配置
--               写端点闸门 require_agent_manage 的运行期消费面）。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0033_employee_governance_manage
--
-- 存量行语义：新增列全部带默认值（private + 空名单），既有治理行自动落
-- 最严语义，仅创建者/admin/team_lead 可配，无越权放开。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_granted_departments JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_granted_users JSONB NOT NULL DEFAULT '[]'::jsonb;

-- CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_employee_governance_manage_visibility'
    ) THEN
        ALTER TABLE employee_governance ADD CONSTRAINT
        ck_employee_governance_manage_visibility
        CHECK (manage_visibility IN ('private', 'department'));
    END IF;
END
$$;

COMMENT ON COLUMN employee_governance.manage_visibility IS
    '可配置范围（后台配置域授权维）: private-仅创建者可配（默认）, '
    'department-部门可配（归属 ∪ 管理授权部门）；不支持 org，'
    '全员可配用 team_lead 角色（agent:manage）表达';
COMMENT ON COLUMN employee_governance.manage_granted_departments IS
    '管理授权部门 id 数组（manage_visibility=department 时生效，'
    '写入时展开子树投影为 dept:{path} team 集合）';
COMMENT ON COLUMN employee_governance.manage_granted_users IS
    '管理授权用户名单（显式 usernames；与创建者并集恒可配，'
    '覆盖"个别跨部门人员可配"与全员可配的兜底表达）';
