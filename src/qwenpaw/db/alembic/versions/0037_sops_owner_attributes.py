# -*- coding: utf-8 -*-
"""SOP owner attribution columns (department/project snapshot).

Revision ID: 0037_sops_owner_attributes
Revises: 0036_agent_skill_bundles
Create Date: 2026-09-17

``sops`` 增加归属快照两列（S2 个人资产的业务域归属；SOP 私有能力化后
``owner_id`` = 归属员工 id）：

- ``department_id``：owner 部门归属快照（写入时经 org 目录解析的部门
  path：员工 owner 取其治理行归属部门，用户名 owner 按部门成员解析；
  无 PG 或 owner 无部门时为空）。行诞生即快照，随 promote/fork/rollback
  复制，不随重复发布抖动；
- ``project_id``：owner 项目归属快照（预留列；SOP 暂无项目维度，恒空）。

两列为普通可查询投影（非 JSONB 内字段）：ops 按部门检索/归属统计用。
存量行两列为 NULL，无越权语义变化（可见性仍由 environment + owner_id
决定：“个人 draft 仅 owner、production 全员”）。全部 DDL 幂等
（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

（psql twin: changelog 20260917/05，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0037_sops_owner_attributes"
down_revision = "0036_agent_skill_bundles"
branch_labels = None
depends_on = None

# 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
_ADD_COLUMNS = (
    "ALTER TABLE sops ADD COLUMN IF NOT EXISTS department_id TEXT",
    "ALTER TABLE sops ADD COLUMN IF NOT EXISTS project_id TEXT",
)

# 归属检索索引（tenant + department）：ops 按部门检索/归属统计走此
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_sops_department "
    "ON sops (tenant_id, department_id)",
)

_COMMENTS = (
    "COMMENT ON COLUMN sops.department_id IS "
    "'owner 部门归属快照（写入时经 org 目录解析的部门 path；员工 owner "
    "取治理行归属部门，用户名 owner 按部门成员解析；无 PG 或 owner 无"
    "部门时为空；ops 按部门检索/归属统计用）'",
    "COMMENT ON COLUMN sops.project_id IS "
    "'owner 项目归属快照（预留列；SOP 暂无项目维度，恒空）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sops_department")
    op.execute("ALTER TABLE sops DROP COLUMN IF EXISTS project_id")
    op.execute("ALTER TABLE sops DROP COLUMN IF EXISTS department_id")
