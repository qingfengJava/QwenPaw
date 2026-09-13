# -*- coding: utf-8 -*-
"""Cron task ledger unify (对话创建任务入台账 + run_id 贯通执行记录).

Revision ID: 0029_cron_task_ledger_unify
Revises: 0028_inbox_events_pg
Create Date: 2026-09-13

定时任务域三表扩展，打通「对话创建 → 统一台账 → 执行记录对齐会话日志」：

- ``expert_scheduled_tasks`` 增列 ``source``（任务来源: ui-界面创建,
  chat-对话创建, api-开放接口）与 ``origin``（来源端原始载荷投影），
  台账从「UI 管理投影」升级为数字员工全部定时任务的统一台账——
  对话创建链路（slash cron-create → CronManager）经注册观察者自动
  投影入账，列表/筛选/统计单一出口；
- ``expert_task_runs`` 增列 ``run_id``（关联 agent_runs 的运行 ID）
  与 ``session_id``（执行会话），列表行保持轻量，详情层直接复用
  agent_runs/agent_run_spans 的会话日志权威结构（span 树 + 回放）；
- ``agent_runs`` 增列 ``cron_job_id``（定时任务执行反查键），配合
  RunLogStartHook 的 source 修正（cron 来源不再误标为 chat）。

（psql twin: changelog 20260913/03，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0029_cron_task_ledger_unify"
down_revision = "0028_inbox_events_pg"
branch_labels = None
depends_on = None

# 幂等加列（存量库补列 / 新库 CREATE TABLE 后补齐，双路径安全）
_BACKFILL_DDLS = (
    "ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS "
    "source VARCHAR(16) NOT NULL DEFAULT 'ui'",
    "ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS "
    "origin JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS "
    "run_id VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS "
    "session_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS "
    "cron_job_id VARCHAR(64)",
)

# CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
_ADD_SOURCE_CHECK = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_expert_scheduled_tasks_source'
    ) THEN
        ALTER TABLE expert_scheduled_tasks ADD CONSTRAINT
        ck_expert_scheduled_tasks_source
        CHECK (source IN ('ui', 'chat', 'api'));
    END IF;
END
$$;
"""

_CREATE_INDEXES = (
    # 台账按来源筛选（对话创建/界面创建分流列表）
    "CREATE INDEX IF NOT EXISTS idx_expert_scheduled_tasks_source "
    "ON expert_scheduled_tasks (tenant_id, expert_id, source)",
    # 执行记录 → agent_runs 运行详情跳转键（空串历史行不进索引）
    "CREATE INDEX IF NOT EXISTS idx_expert_task_runs_run "
    "ON expert_task_runs (tenant_id, run_id) WHERE run_id <> ''",
    # 运行日志按定时任务反查（cron 执行记录的权威结构入口）
    "CREATE INDEX IF NOT EXISTS ix_agent_runs_cron_job "
    "ON agent_runs (tenant_id, cron_job_id, started_at) "
    "WHERE cron_job_id IS NOT NULL",
)

_COMMENTS = (
    "COMMENT ON COLUMN expert_scheduled_tasks.source IS "
    "'任务来源: ui-界面创建, chat-对话创建, api-开放接口创建"
    "（注册观察者自动投影，统一台账单一出口）'",
    "COMMENT ON COLUMN expert_scheduled_tasks.origin IS "
    "'来源端原始载荷投影 JSONB（对话创建时保留 CronJobSpec 关键字段"
    "如 dispatch/channel，便于溯源）'",
    "COMMENT ON COLUMN expert_task_runs.run_id IS "
    "'关联 agent_runs 的运行 ID（详情层复用会话日志权威结构："
    "span 树 + 会话回放；历史行为空串）'",
    "COMMENT ON COLUMN expert_task_runs.session_id IS "
    "'本次执行落库的会话 ID（share_session=false 时为 cron:{job_id} "
    "独立会话）'",
    "COMMENT ON COLUMN agent_runs.cron_job_id IS "
    "'定时任务 ID（source=cron 的执行反查键；会话执行为 NULL）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260913/03 的等价 alembic 路径）
    for ddl in _BACKFILL_DDLS:
        op.execute(ddl)
    op.execute(_ADD_SOURCE_CHECK)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 清理顺序：先索引后列（列上索引依赖列）
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_cron_job")
    op.execute("DROP INDEX IF EXISTS idx_expert_task_runs_run")
    op.execute("DROP INDEX IF EXISTS idx_expert_scheduled_tasks_source")
    op.execute(
        "ALTER TABLE agent_runs DROP COLUMN IF EXISTS cron_job_id",
    )
    op.execute("ALTER TABLE expert_task_runs DROP COLUMN IF EXISTS session_id")
    op.execute("ALTER TABLE expert_task_runs DROP COLUMN IF EXISTS run_id")
    op.execute(
        "ALTER TABLE expert_scheduled_tasks "
        "DROP CONSTRAINT IF EXISTS ck_expert_scheduled_tasks_source",
    )
    op.execute(
        "ALTER TABLE expert_scheduled_tasks DROP COLUMN IF EXISTS origin",
    )
    op.execute(
        "ALTER TABLE expert_scheduled_tasks DROP COLUMN IF EXISTS source",
    )
