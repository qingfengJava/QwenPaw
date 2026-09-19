-- [变更说明] RBAC 权限管理体系 PG 化 - 新建 9 张核心表
-- [变更时间] 2026-09-19
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
--
-- 背景：权限元数据原为 rbac.json 文件存储，升级为 PostgreSQL 权威存储
-- （接口不变，无 PG 部署继续走文件路径）。新建 9 张核心表：角色、权限、
-- 角色-权限关联、用户-角色关联、菜单、角色-菜单关联、数据范围规则、
-- 团队、团队成员关联。
-- 全部 CREATE TABLE / INDEX IF NOT EXISTS，幂等；ID 字段 VARCHAR(64)
-- （应用侧 shortuuid 生成）；时间字段 TIMESTAMPTZ；tenant_id 默认 'default'。
-- alembic twin: 0042_rbac_pg_schema

-- 角色主表（多租户，name 租户内唯一）
CREATE TABLE IF NOT EXISTS rbac_roles (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    id          VARCHAR(64)  NOT NULL,
    name        VARCHAR(64)  NOT NULL,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    description TEXT         NOT NULL DEFAULT '',
    is_builtin  BOOLEAN      NOT NULL DEFAULT FALSE,
    is_enabled  BOOLEAN      NOT NULL DEFAULT TRUE,
    data_scope  VARCHAR(32)  NOT NULL DEFAULT 'self',
    sort_order  INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
);

-- 权限注册表（code 租户内唯一，resource/action 维度）
CREATE TABLE IF NOT EXISTS rbac_permissions (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    id          VARCHAR(64)  NOT NULL,
    code        VARCHAR(128) NOT NULL,
    name        VARCHAR(128) NOT NULL DEFAULT '',
    resource    VARCHAR(64)  NOT NULL,
    action      VARCHAR(64)  NOT NULL,
    perm_type   VARCHAR(16)  NOT NULL DEFAULT 'api',
    description TEXT         NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, code)
);

-- 角色-权限关联
CREATE TABLE IF NOT EXISTS rbac_role_permissions (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    role_id     VARCHAR(64)  NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_id, permission_id)
);

-- 用户-角色关联
CREATE TABLE IF NOT EXISTS rbac_user_roles (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    username    VARCHAR(64)  NOT NULL,
    role_id     VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, username, role_id)
);
CREATE INDEX IF NOT EXISTS ix_rbac_user_roles_username ON rbac_user_roles(tenant_id, username);

-- 菜单表（树形，parent_id 自关联）
CREATE TABLE IF NOT EXISTS rbac_menus (
    tenant_id    VARCHAR(64)  NOT NULL DEFAULT 'default',
    id           VARCHAR(64)  NOT NULL,
    parent_id    VARCHAR(64),
    name         VARCHAR(128) NOT NULL,
    menu_type    VARCHAR(16)  NOT NULL DEFAULT 'menu',
    path         VARCHAR(256) NOT NULL DEFAULT '',
    component    VARCHAR(256) NOT NULL DEFAULT '',
    icon         VARCHAR(64)  NOT NULL DEFAULT '',
    perm_code    VARCHAR(128) NOT NULL DEFAULT '',
    sort_order   INTEGER      NOT NULL DEFAULT 0,
    is_visible   BOOLEAN      NOT NULL DEFAULT TRUE,
    is_enabled   BOOLEAN      NOT NULL DEFAULT TRUE,
    is_external  BOOLEAN      NOT NULL DEFAULT FALSE,
    redirect     VARCHAR(256) NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS ix_rbac_menus_parent ON rbac_menus(tenant_id, parent_id);

-- 角色-菜单关联
CREATE TABLE IF NOT EXISTS rbac_role_menus (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    role_id     VARCHAR(64)  NOT NULL,
    menu_id     VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_id, menu_id)
);

-- 数据范围规则表（role × resource 唯一）
CREATE TABLE IF NOT EXISTS rbac_data_scopes (
    tenant_id    VARCHAR(64)  NOT NULL DEFAULT 'default',
    id           VARCHAR(64)  NOT NULL,
    role_id      VARCHAR(64)  NOT NULL,
    resource     VARCHAR(64)  NOT NULL,
    scope_type   VARCHAR(32)  NOT NULL DEFAULT 'self',
    custom_dept_ids JSONB     NOT NULL DEFAULT '[]',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, role_id, resource)
);

-- 用户组/团队表
CREATE TABLE IF NOT EXISTS rbac_teams (
    tenant_id    VARCHAR(64)  NOT NULL DEFAULT 'default',
    id           VARCHAR(64)  NOT NULL,
    name         VARCHAR(64)  NOT NULL,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    description  TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name)
);

-- 团队成员关联
CREATE TABLE IF NOT EXISTS rbac_team_members (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    team_id     VARCHAR(64)  NOT NULL,
    username    VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, team_id, username)
);
CREATE INDEX IF NOT EXISTS ix_rbac_team_members_user ON rbac_team_members(tenant_id, username);
