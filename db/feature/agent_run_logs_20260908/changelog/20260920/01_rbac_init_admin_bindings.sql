-- [变更说明] 企业级 RBAC 初始化 - 用户↔角色绑定回填 + 默认超管保护位置位
-- [变更时间] 2026-09-20
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
--
-- 背景：20260919 RBAC PG 化（changelog/20260919/01_rbac_pg_schema.sql）后，
-- 启动 seed 契约仅覆盖权限/内置角色/菜单/角色-菜单四类元数据，未覆盖
-- "用户↔角色绑定"（rbac_user_roles），导致存量账号与新建超管均无绑定行，
-- /auth/menus、/auth/permissions 恒为空。本变更（全部幂等，可重复执行）：
--   1) 为"零绑定"用户按 flat role 映射补齐 rbac_user_roles
--      （admin→platform_admin、employee→employee）；已有绑定的用户不
--      覆盖（保护运营的显式授权/降级）；
--   2) 内置默认超管 admin 若存在则置 is_superadmin=TRUE（列已在 0043
--      就绪；语义与 seed_default_admin 一致：禁止被禁用/降级）。
-- 说明：admin 账号本体由管理接口 POST /api/admin/users 创建（口令需应用侧
-- argon2id 散列，SQL 无法生成）；空库部署由应用启动 seed_default_admin
-- 自动创建，不依赖本文件。
-- 运行时防复发：应用侧 seed 同步增补 _seed_user_roles（第 5 步），
-- 启动即自动补齐绑定（与下方 SQL 同构）。

-- 1) 用户↔角色绑定回填（仅"零绑定"用户，按 flat role 映射）
INSERT INTO rbac_user_roles (username, role_id)
SELECT u.username, r.id
FROM qwenpaw_users u
JOIN rbac_roles r
  ON r.tenant_id = u.tenant_id
 AND r.name = CASE u.role
        WHEN 'admin'    THEN 'platform_admin'
        WHEN 'employee' THEN 'employee'
   END
WHERE NOT EXISTS (
    SELECT 1 FROM rbac_user_roles ur
    WHERE ur.tenant_id = u.tenant_id AND ur.username = u.username
)
ON CONFLICT DO NOTHING;

-- 2) 默认超管保护位置位（幂等）
UPDATE qwenpaw_users
SET is_superadmin = TRUE
WHERE tenant_id = 'default'
  AND username = 'admin'
  AND is_superadmin = FALSE;

-- 验证（手工执行）：
-- SELECT ur.username, r.name FROM rbac_user_roles ur
-- JOIN rbac_roles r ON r.tenant_id = ur.tenant_id AND r.id = ur.role_id;
-- SELECT username, is_superadmin FROM qwenpaw_users WHERE username = 'admin';