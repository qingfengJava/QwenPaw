# -*- coding: utf-8 -*-
"""Cron ledger convergence Phase 1: history detail columns + run_count.

Revision ID: 0040_cron_ledger_expand
Revises: 0039_driver_cards_credentials
Create Date: 2026-09-18

T13 cron 双台账收口 Phase 1（EXPAND，设计文档 docs/design/
2026-09-18-cron-ledger-convergence.md）：expert 两表收口进 cron
双表之前，权威面必须先承载 expert 台账的全部读字段——

``cron_job_history`` 补 4 列（执行留痕明细）：

- ``result_summary``：本次执行最终输出摘要（worklog 时间线标题来源）；
- ``run_id`` / ``session_id``：关联 agent_runs 运行详情与会话回放的
  跳转键（CronExecutionRecord 模型早有此二字段且 manager 已赋值，
  但 pg_repo 的 INSERT 一直丢列——本次补齐落库面）；
- ``scheduled_for``：调度槽位时间（trigger=scheduled 时取 run_at，
  手动触发为空），保留 expert 台账幂等锚语义。

``cron_jobs`` 补 1 列：

- ``run_count``：历史累计执行次数冗余计数（append_history 同事务
  +1；execution history 只保留最近 50 条，COUNT 反推会被修剪窗
  截断，故落冗余列保精确——决策 D3）。

写路径补列对老代码零影响（新列均有默认值，旧 SELECT 不读新列）；
alembic downgrade 0040 即 Phase 1 回滚面。全部 DDL 幂等
（ADD COLUMN IF NOT EXISTS）。
（psql twin: changelog 20260918/03，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0040_cron_ledger_expand"
down_revision = "0039_driver_cards_credentials"
branch_labels = None
depends_on = None

_ADD_HISTORY_COLUMNS = (
    "ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS "
    "result_summary TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS "
    "run_id VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS "
    "session_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS "
    "scheduled_for TIMESTAMPTZ",
)

_ADD_JOBS_COLUMNS = (
    "ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS "
    "run_count INTEGER NOT NULL DEFAULT 0",
)

_COMMENTS = (
    "COMMENT ON COLUMN cron_job_history.result_summary IS "
    "'执行结果摘要（final_text 截断 500 字，worklog 时间线标题来源）'",
    "COMMENT ON COLUMN cron_job_history.run_id IS "
    "'关联 agent_runs 的运行 ID（执行详情跳转键；text 任务为空）'",
    "COMMENT ON COLUMN cron_job_history.session_id IS "
    "'本次执行落库的会话 ID（share_session=False 时为 cron:{job_id}，"
    "会话回放跳转键）'",
    "COMMENT ON COLUMN cron_job_history.scheduled_for IS "
    "'调度槽位时间（trigger=scheduled 时等于 run_at，手动触发为空）'",
    "COMMENT ON COLUMN cron_jobs.run_count IS "
    "'历史累计执行次数（append_history 同事务 +1；history 仅留最近 "
    "50 条，精确计数不能靠 COUNT 反推）'",
)


def upgrade() -> None:
    # 幂等补列（psql changelog 20260918/03 的等价 alembic 路径）
    for statement in _ADD_HISTORY_COLUMNS:
        op.execute(statement)
    for statement in _ADD_JOBS_COLUMNS:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("ALTER TABLE cron_jobs DROP COLUMN IF EXISTS run_count")
    op.execute(
        "ALTER TABLE cron_job_history DROP COLUMN IF EXISTS scheduled_for"
    )
    op.execute(
        "ALTER TABLE cron_job_history DROP COLUMN IF EXISTS session_id"
    )
    op.execute(
        "ALTER TABLE cron_job_history DROP COLUMN IF EXISTS run_id"
    )
    op.execute(
        "ALTER TABLE cron_job_history "
        "DROP COLUMN IF EXISTS result_summary"
    )
