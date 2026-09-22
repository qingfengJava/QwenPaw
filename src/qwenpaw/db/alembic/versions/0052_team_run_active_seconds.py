# -*- coding: utf-8 -*-
"""Team run cumulative active execution seconds (SLA across resumes).

Revision ID: 0052_team_run_active_seconds
Revises: 0051_team_run_action_ledger
Create Date: 2026-09-22

专家团职责协作 T5（有界调度/取消恢复/计量闭环）：

- ``team_runs.active_seconds``：累计活跃执行时间（秒）——各执行段
  在引擎收尾时累加，暂停/中断/续跑**不清零**；时间熔断按
  "累计 + 本段耗时"判定（协议8.5：恢复不清零，人工等待不计时）。

幂等 DDL。（psql twin: changelog 20260921/04）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0052_team_run_active_seconds"
down_revision = "0051_team_run_action_ledger"
branch_labels = None
depends_on = None

_ALTER = (
    "ALTER TABLE team_runs ADD COLUMN IF NOT EXISTS active_seconds "
    "INTEGER NOT NULL DEFAULT 0"
)

_COMMENT = (
    "COMMENT ON COLUMN team_runs.active_seconds IS "
    "'累计活跃执行时间秒(T5): 各执行段累加, 恢复/续跑不清零, "
    "时间熔断按累计值判定'"
)


def upgrade() -> None:
    # 补列（幂等）
    op.execute(_ALTER)
    # 注释
    op.execute(_COMMENT)


def downgrade() -> None:
    op.execute("ALTER TABLE team_runs DROP COLUMN IF EXISTS active_seconds")
