-- ============================================================
-- 变更说明: 新增 xian_workspaces 表 —— XianWork 用户工作空间登记表
--           （空间 = 用户注册的磁盘目录容器；会话绑定复用既有
--            chats.meta.runtime_context.project_dir 机制，
--            本表只登记「目录 → 命名空间」映射，不改 chats 表结构；
--            侧边栏任务/空间分组按 dir_path 与会话 project_dir
--            在服务端 normalize 后匹配）
-- 变更时间: 2026-08-16
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0006_xian_workspaces（Revises 0005_media_files）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. XianWork 工作空间登记表
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xian_workspaces (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    id         VARCHAR(64) NOT NULL,
    owner_id   TEXT NOT NULL,
    name       TEXT NOT NULL,
    dir_path   TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_xian_workspaces PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE xian_workspaces IS 'XianWork 用户工作空间登记表（空间=用户注册的磁盘目录容器；绑定关系存于 chats.meta.runtime_context.project_dir，本表不存会话外键）';
COMMENT ON COLUMN xian_workspaces.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN xian_workspaces.id IS '工作空间 ID（业务侧生成 UUID，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN xian_workspaces.owner_id IS '归属账号（xian 面 username，RLS owner_isolation 隔离键）';
COMMENT ON COLUMN xian_workspaces.name IS '工作空间显示名（侧边栏空间区文件夹标题）';
COMMENT ON COLUMN xian_workspaces.dir_path IS '工作空间磁盘目录绝对路径（服务端 expanduser().resolve() 规范化后落库；会话 project_dir 与本列匹配即视为已绑定）';
COMMENT ON COLUMN xian_workspaces.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN xian_workspaces.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE UNIQUE INDEX IF NOT EXISTS ux_xian_workspaces_owner_dir
    ON xian_workspaces (tenant_id, owner_id, dir_path);

CREATE INDEX IF NOT EXISTS ix_xian_workspaces_owner
    ON xian_workspaces (tenant_id, owner_id);

-- ------------------------------------------------------------
-- 2. Owner 隔离 RLS（PERMISSIVE 灰度策略；无 DROP 语句的幂等形态）
-- ------------------------------------------------------------

ALTER TABLE xian_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE xian_workspaces FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'xian_workspaces' AND policyname = 'owner_isolation'
    ) THEN
        EXECUTE format(
            'CREATE POLICY owner_isolation ON %I AS PERMISSIVE FOR ALL USING (%s) WITH CHECK (%s)',
            'xian_workspaces',
            'current_setting(''app.current_owner'', true) IS NULL ' ||
            'OR current_setting(''app.current_owner'', true) = '''' ' ||
            'OR owner_id IS NULL ' ||
            'OR owner_id = current_setting(''app.current_owner'', true)',
            'current_setting(''app.current_owner'', true) IS NULL ' ||
            'OR current_setting(''app.current_owner'', true) = '''' ' ||
            'OR owner_id IS NULL ' ||
            'OR owner_id = current_setting(''app.current_owner'', true)'
        );
    END IF;
END $$;

-- ------------------------------------------------------------
-- 3. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0006_xian_workspaces';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0006_xian_workspaces');
    END IF;
END $$;

COMMIT;
