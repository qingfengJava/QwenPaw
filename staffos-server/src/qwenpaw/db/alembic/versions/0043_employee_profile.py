# -*- coding: utf-8 -*-
"""Employee profile columns on qwenpaw_users.

Revision ID: 0043_employee_profile
Revises: 0042_rbac_pg_schema
Create Date: 2026-09-19

企业级 RBAC 组织与权限升级：为账号主表补齐"部门员工"管理所需的员工档案
字段（对照企业后台"部门员工"页：姓名/手机号/性别/职位/超管标记）。这些
字段仅用于后台组织管理展示与筛选，登录身份锚点仍是 username（不可变）：

- ``real_name``：员工姓名（列表主展示列，display_name 保留为登录显示名）；
- ``phone``：手机号（关键字搜索命中列之一）；
- ``gender``：性别 0未知/1男/2女（枚举，前端转描述文本展示）；
- ``position``：职位；
- ``is_superadmin``：超管标记（列表红色徽章 + Service 层保护：禁止被禁用/
  删除/降级，默认超级管理员账号置此标记）。

全部 ADD COLUMN IF NOT EXISTS，幂等；补 COMMENT；新增 (tenant_id, disabled)
复合索引服务部门员工列表的"按部门 + 状态"筛选高频路径。

（psql twin: changelog 20260919/02，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0043_employee_profile"
down_revision = "0042_rbac_pg_schema"
branch_labels = None
depends_on = None

# 员工档案补列（幂等：ADD COLUMN IF NOT EXISTS）
_ADD_COLUMNS = (
    "ALTER TABLE qwenpaw_users "
    "ADD COLUMN IF NOT EXISTS real_name VARCHAR(128) NOT NULL DEFAULT ''",
    "ALTER TABLE qwenpaw_users "
    "ADD COLUMN IF NOT EXISTS phone VARCHAR(32) NOT NULL DEFAULT ''",
    "ALTER TABLE qwenpaw_users "
    "ADD COLUMN IF NOT EXISTS gender SMALLINT NOT NULL DEFAULT 0",
    "ALTER TABLE qwenpaw_users "
    "ADD COLUMN IF NOT EXISTS position VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE qwenpaw_users "
    "ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN NOT NULL DEFAULT FALSE",
)

# 列备注 + 部门员工列表筛选索引
_COMMENTS_AND_INDEXES = (
    "COMMENT ON COLUMN qwenpaw_users.real_name IS "
    "'员工姓名（部门员工列表主展示列，区别于登录显示名 display_name）'",
    "COMMENT ON COLUMN qwenpaw_users.phone IS "
    "'手机号（部门员工列表关键字搜索命中列）'",
    "COMMENT ON COLUMN qwenpaw_users.gender IS "
    "'性别: 0-未知, 1-男, 2-女（前端转描述文本展示）'",
    "COMMENT ON COLUMN qwenpaw_users.position IS '职位'",
    "COMMENT ON COLUMN qwenpaw_users.is_superadmin IS "
    "'超管标记: TRUE 时禁止被禁用/删除/降级，默认超级管理员账号置此标记'",
    # 部门员工列表"按状态筛选"高频路径（配合 department_members JOIN）。
    "CREATE INDEX IF NOT EXISTS ix_qwenpaw_users_tenant_disabled "
    "ON qwenpaw_users (tenant_id, disabled)",
)


def upgrade() -> None:
    """Add employee-profile columns + filter index (idempotent)."""
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    for statement in _COMMENTS_AND_INDEXES:
        op.execute(statement)


def downgrade() -> None:
    """Drop the employee-profile columns + index added by this revision."""
    op.execute("DROP INDEX IF EXISTS ix_qwenpaw_users_tenant_disabled")
    for column in (
        "is_superadmin",
        "position",
        "gender",
        "phone",
        "real_name",
    ):
        op.execute(
            f"ALTER TABLE qwenpaw_users DROP COLUMN IF EXISTS {column}"
        )
