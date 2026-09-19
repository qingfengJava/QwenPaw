-- [变更说明] 企业级 RBAC 组织权限升级 - qwenpaw_users 补员工档案字段
-- [变更时间] 2026-09-19
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0043_employee_profile
--
-- 背景：为账号主表补齐"部门员工"管理所需的员工档案字段（姓名/手机号/
-- 性别/职位/超管标记）。登录身份锚点仍是 username（不可变），这些字段
-- 仅用于后台组织管理展示与筛选。全部 ADD COLUMN IF NOT EXISTS，幂等。

ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS real_name    VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS phone        VARCHAR(32)  NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS gender       SMALLINT     NOT NULL DEFAULT 0;
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS position     VARCHAR(64)  NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN     NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN qwenpaw_users.real_name IS '员工姓名（部门员工列表主展示列，区别于登录显示名 display_name）';
COMMENT ON COLUMN qwenpaw_users.phone IS '手机号（部门员工列表关键字搜索命中列）';
COMMENT ON COLUMN qwenpaw_users.gender IS '性别: 0-未知, 1-男, 2-女（前端转描述文本展示）';
COMMENT ON COLUMN qwenpaw_users.position IS '职位';
COMMENT ON COLUMN qwenpaw_users.is_superadmin IS '超管标记: TRUE 时禁止被禁用/删除/降级，默认超级管理员账号置此标记';

-- 部门员工列表"按状态筛选"高频路径（配合 department_members JOIN）
CREATE INDEX IF NOT EXISTS ix_qwenpaw_users_tenant_disabled ON qwenpaw_users (tenant_id, disabled);
