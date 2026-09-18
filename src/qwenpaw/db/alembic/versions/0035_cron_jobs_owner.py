# -*- coding: utf-8 -*-
"""Cron jobs personal-ownership columns (S2 user-personal plane).

Revision ID: 0035_cron_jobs_owner
Revises: 0034_kb_pg_plane
Create Date: 2026-09-17

``cron_jobs`` 增加个人任务归属三列（双平面模型的 S2 用户个人平面）：

- ``owner_user_id``：非空=个人任务（仅 owner + 平台管理员可见可改，跨人
  严格隔离）；为空=员工共享任务（S1，使用授权内全员可见、员工级管理
  授权者可写）；
- ``department_id``：owner 部门归属快照（写入时经 org 目录解析的部门 path，
  ops 按部门检索/归属统计用；无 PG 或 owner 无部门时为空）；
- ``project_id``：owner 项目归属快照（预留列；个人定时任务暂无项目维度）。

三列均为 ``spec`` JSONB 内 CronJobSpec 同名字段的可查询投影——权威仍在
spec（随 json/pg 两平面往返），投影列仅供运维按 owner/部门检索，不必解
JSONB。存量行 owner 为 NULL → 自动落"员工共享"语义，与既有全员可见行为
一致，无越权收紧。全部 DDL 幂等（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

（psql twin: changelog 20260917/03，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0035_cron_jobs_owner"
down_revision = "0034_kb_pg_plane"
branch_labels = None
depends_on = None

_ADD_COLUMNS = (
    "ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS owner_user_id TEXT",
    "ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS department_id TEXT",
    "ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS project_id TEXT",
)

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_cron_jobs_owner "
    "ON cron_jobs (tenant_id, agent_id, owner_user_id)",
)

_COMMENTS = (
    "COMMENT ON COLUMN cron_jobs.owner_user_id IS "
    "'个人任务归属用户（spec.owner_user_id 的可查询投影）: 非空=个人任务"
    "（仅 owner+平台管理员可见可改，跨人隔离）, 空=员工共享任务"
    "（使用授权内全员可见、员工级管理授权者可写）'",
    "COMMENT ON COLUMN cron_jobs.department_id IS "
    "'owner 部门归属快照（写入时经 org 目录解析的部门 path；无 PG 或"
    "owner 无部门时为空；ops 按部门检索/归属统计用）'",
    "COMMENT ON COLUMN cron_jobs.project_id IS "
    "'owner 项目归属快照（预留列；个人定时任务暂无项目维度，恒空）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cron_jobs_owner")
    op.execute("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS project_id")
    op.execute("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS department_id")
    op.execute("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS owner_user_id")
