# -*- coding: utf-8 -*-
"""User accounts to PostgreSQL (qwenpaw_users + identity bindings).

Revision ID: 0032_user_accounts_pg
Revises: 0031_employee_governance
Create Date: 2026-09-16

账号体系 M2 里程碑：users.json 文件存储升级为 PG 权威存储（接口不变，
无 PG 部署继续走文件路径）：

- ``qwenpaw_users``：账号主表（username 不可变身份锚点，argon2id 密码
  散列 + 资料/角色/org 字段）；启动时文件存量幂等导入一次；
- ``user_identity_bindings``：渠道外部身份 → 账号绑定（M1 存于
  users.json 的 identity_bindings 字典，迁 PG 后按表存储）；
- ``agent_runs`` 补 user 筛选索引（employee「仅看自己」数据权限的
  高频查询路径）。

（psql twin: changelog 20260916/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0032_user_accounts_pg"
down_revision = "0031_employee_governance"
branch_labels = None
depends_on = None

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS qwenpaw_users (
    tenant_id     VARCHAR(64)  NOT NULL DEFAULT 'default',
    username      VARCHAR(64)  NOT NULL,
    password_hash TEXT         NOT NULL,
    password_salt VARCHAR(64)  NOT NULL DEFAULT '',
    password_algo VARCHAR(16)  NOT NULL DEFAULT 'argon2',
    role          VARCHAR(16)  NOT NULL DEFAULT 'employee',
    display_name  VARCHAR(128) NOT NULL DEFAULT '',
    avatar        VARCHAR(512) NOT NULL DEFAULT '',
    disabled      BOOLEAN      NOT NULL DEFAULT FALSE,
    org_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_qwenpaw_users PRIMARY KEY (tenant_id, username)
)
"""

_CREATE_BINDINGS = """
CREATE TABLE IF NOT EXISTS user_identity_bindings (
    tenant_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    channel          VARCHAR(32)  NOT NULL,
    external_user_id VARCHAR(128) NOT NULL,
    username         VARCHAR(64)  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_identity_bindings
        PRIMARY KEY (tenant_id, channel, external_user_id)
)
"""

_COMMENTS_AND_INDEXES = (
    "COMMENT ON TABLE qwenpaw_users IS "
    "'账号主表（M2 权威存储；users.json 保留为无 PG 部署回退）'",
    "COMMENT ON COLUMN qwenpaw_users.username IS "
    "'用户名（不可变身份锚点：会话/记忆/运行日志按此归属）'",
    "COMMENT ON COLUMN qwenpaw_users.password_algo IS "
    "'密码散列算法: argon2, sha256（legacy，登录时透明升级）'",
    "COMMENT ON COLUMN qwenpaw_users.role IS '角色: admin, employee'",
    "COMMENT ON COLUMN qwenpaw_users.org_id IS "
    "'归属组织（租户预留；部门成员关系在 department_members）'",
    "COMMENT ON TABLE user_identity_bindings IS "
    "'渠道外部身份 → 账号绑定（wechat:openid 等映射到注册用户名）'",
    "COMMENT ON COLUMN user_identity_bindings.external_user_id IS "
    "'渠道侧用户标识（openid/userid 等，渠道内唯一）'",
    # 运行日志按发起用户筛选/权限过滤的高频路径（employee 仅看自己）。
    "CREATE INDEX IF NOT EXISTS ix_agent_runs_user "
    "ON agent_runs (tenant_id, agent_id, user_id, started_at) "
    "WHERE user_id IS NOT NULL",
)


def upgrade() -> None:
    """Create the PG-backed account tables (idempotent)."""
    op.execute(_CREATE_USERS)
    op.execute(_CREATE_BINDINGS)
    for statement in _COMMENTS_AND_INDEXES:
        op.execute(statement)


def downgrade() -> None:
    """Drop the PG-backed account tables (file store remains the fallback)."""
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_user")
    op.execute("DROP TABLE IF EXISTS user_identity_bindings")
    op.execute("DROP TABLE IF EXISTS qwenpaw_users")
