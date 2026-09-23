# -*- coding: utf-8 -*-
"""Employee governance manage-scope columns (backend configuration plane).

Revision ID: 0033_employee_governance_manage
Revises: 0032_user_accounts_pg
Create Date: 2026-09-17

``employee_governance`` 增加后台配置域授权三列（双平面模型的 manage 维）：

- ``manage_visibility`` 两级：``private``-仅创建者可配（默认，最严出厂）/
  ``department``-部门可配（归属 ∪ 管理授权部门）；不支持 ``org``
  （"全员可配"用 team_lead 角色 ``agent:manage`` 表达，避免误配）；
- ``manage_granted_departments`` / ``manage_granted_users``：管理授权部门
  与显式授权用户名单（后者兜底"个别跨部门人员可配"场景）；
- 治理写入由服务层投影到 RBAC ``agent_manage_grants``，S1 共享配置写
  端点闸门 ``require_agent_manage`` 只消费投影面，本表不进请求路径。

存量行语义：三列全部带默认值（private + 空名单），既有治理行自动落最严
语义，仅创建者/admin/team_lead 可配，无越权放开。

（psql twin: changelog 20260917/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0033_employee_governance_manage"
down_revision = "0032_user_accounts_pg"
branch_labels = None
depends_on = None

_ADD_COLUMNS = (
    "ALTER TABLE employee_governance ADD COLUMN IF NOT EXISTS "
    "manage_visibility VARCHAR(16) NOT NULL DEFAULT 'private'",
    "ALTER TABLE employee_governance ADD COLUMN IF NOT EXISTS "
    "manage_granted_departments JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE employee_governance ADD COLUMN IF NOT EXISTS "
    "manage_granted_users JSONB NOT NULL DEFAULT '[]'::jsonb",
)

# CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
_ADD_MANAGE_VISIBILITY_CHECK = """
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
"""

_COMMENTS = (
    "COMMENT ON COLUMN employee_governance.manage_visibility IS "
    "'可配置范围（后台配置域授权维）: private-仅创建者可配（默认）, "
    "department-部门可配（归属 ∪ 管理授权部门）；不支持 org，"
    "全员可配用 team_lead 角色（agent:manage）表达'",
    "COMMENT ON COLUMN employee_governance.manage_granted_departments IS "
    "'管理授权部门 id 数组（manage_visibility=department 时生效，"
    "写入时展开子树投影为 dept:{path} team 集合）'",
    "COMMENT ON COLUMN employee_governance.manage_granted_users IS "
    "'管理授权用户名单（显式 usernames；与创建者并集恒可配，"
    "覆盖\"个别跨部门人员可配\"与全员可配的兜底表达）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    op.execute(_ADD_MANAGE_VISIBILITY_CHECK)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE employee_governance "
        "DROP CONSTRAINT IF EXISTS ck_employee_governance_manage_visibility"
    )
    op.execute(
        "ALTER TABLE employee_governance "
        "DROP COLUMN IF EXISTS manage_granted_users"
    )
    op.execute(
        "ALTER TABLE employee_governance "
        "DROP COLUMN IF EXISTS manage_granted_departments"
    )
    op.execute(
        "ALTER TABLE employee_governance "
        "DROP COLUMN IF EXISTS manage_visibility"
    )
