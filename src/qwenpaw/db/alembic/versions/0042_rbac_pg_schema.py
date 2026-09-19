# -*- coding: utf-8 -*-
"""RBAC permission system to PostgreSQL (9 core tables).

Revision ID: 0042_rbac_pg_schema
Revises: 0041_drop_expert_ledger
Create Date: 2026-09-19

RBAC 权限管理体系 PG 化：将权限元数据从文件存储（rbac.json）迁移到
PostgreSQL 权威存储，新建 9 张核心表：

- ``rbac_roles``：角色主表（多租户，name 租户内唯一）；
- ``rbac_permissions``：权限注册表（code 租户内唯一，resource/action 维度）；
- ``rbac_role_permissions``：角色-权限关联；
- ``rbac_user_roles``：用户-角色关联；
- ``rbac_menus``：菜单表（树形，parent_id 自关联）；
- ``rbac_role_menus``：角色-菜单关联；
- ``rbac_data_scopes``：数据范围规则表（role × resource 唯一）；
- ``rbac_teams``：用户组/团队表；
- ``rbac_team_members``：团队成员关联。

全部 CREATE TABLE / INDEX IF NOT EXISTS，幂等；ID 字段 VARCHAR(64)
（应用侧 shortuuid 生成）；时间字段 TIMESTAMPTZ（项目既有惯例）；
tenant_id 默认 'default'。

（psql twin: changelog 20260919/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0042_rbac_pg_schema"
down_revision = "0041_drop_expert_ledger"
branch_labels = None
depends_on = None

# --- 角色 / 权限 ---

_CREATE_ROLES = """
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
)
"""

_CREATE_PERMISSIONS = """
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
)
"""

_CREATE_ROLE_PERMISSIONS = """
CREATE TABLE IF NOT EXISTS rbac_role_permissions (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    role_id     VARCHAR(64)  NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_id, permission_id)
)
"""

_CREATE_USER_ROLES = """
CREATE TABLE IF NOT EXISTS rbac_user_roles (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    username    VARCHAR(64)  NOT NULL,
    role_id     VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, username, role_id)
)
"""

# --- 菜单 ---

_CREATE_MENUS = """
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
)
"""

_CREATE_ROLE_MENUS = """
CREATE TABLE IF NOT EXISTS rbac_role_menus (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    role_id     VARCHAR(64)  NOT NULL,
    menu_id     VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, role_id, menu_id)
)
"""

# --- 数据范围 / 团队 ---

_CREATE_DATA_SCOPES = """
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
)
"""

_CREATE_TEAMS = """
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
)
"""

_CREATE_TEAM_MEMBERS = """
CREATE TABLE IF NOT EXISTS rbac_team_members (
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    team_id     VARCHAR(64)  NOT NULL,
    username    VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, team_id, username)
)
"""

# 建表顺序：主表在前，关联表在后
_CREATE_STATEMENTS = (
    _CREATE_ROLES,
    _CREATE_PERMISSIONS,
    _CREATE_ROLE_PERMISSIONS,
    _CREATE_USER_ROLES,
    _CREATE_MENUS,
    _CREATE_ROLE_MENUS,
    _CREATE_DATA_SCOPES,
    _CREATE_TEAMS,
    _CREATE_TEAM_MEMBERS,
)

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_rbac_user_roles_username "
    "ON rbac_user_roles (tenant_id, username)",
    "CREATE INDEX IF NOT EXISTS ix_rbac_menus_parent "
    "ON rbac_menus (tenant_id, parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_rbac_team_members_user "
    "ON rbac_team_members (tenant_id, username)",
)

# DROP 顺序：建表的逆序（关联表在前，主表在后）；CASCADE 连带其索引
_DROP_STATEMENTS = (
    "DROP TABLE IF EXISTS rbac_team_members CASCADE",
    "DROP TABLE IF EXISTS rbac_teams CASCADE",
    "DROP TABLE IF EXISTS rbac_data_scopes CASCADE",
    "DROP TABLE IF EXISTS rbac_role_menus CASCADE",
    "DROP TABLE IF EXISTS rbac_menus CASCADE",
    "DROP TABLE IF EXISTS rbac_user_roles CASCADE",
    "DROP TABLE IF EXISTS rbac_role_permissions CASCADE",
    "DROP TABLE IF EXISTS rbac_permissions CASCADE",
    "DROP TABLE IF EXISTS rbac_roles CASCADE",
)


def upgrade() -> None:
    """Create the 9 RBAC tables + supporting indexes (idempotent)."""
    for statement in _CREATE_STATEMENTS:
        op.execute(statement)
    for statement in _CREATE_INDEXES:
        op.execute(statement)


def downgrade() -> None:
    """Drop the 9 RBAC tables (CASCADE removes dependent indexes)."""
    for statement in _DROP_STATEMENTS:
        op.execute(statement)
