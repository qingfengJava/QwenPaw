# -*- coding: utf-8 -*-
"""Builtin expert catalog columns: sample_tasks + showcase.

Revision ID: 0011_builtin_sample_tasks
Revises: 0010_workforce_team_runs
Create Date: 2026-08-18

Adds the two marketplace/operations JSONB columns to both ``experts``
and ``expert_teams`` (the builtin-expert information architecture):

- ``sample_tasks``: [{title, prompt}] — the "专家帮你做" template list;
  clicking one launches the expert with the prompt as kickoff (single
  expert) or as the run goal (expert team).
- ``showcase``: [{title, desc, tags}] — curated use-case cards
  (admin-editable operations content; expert-team details additionally
  project real "最近交付" from team_runs, the two coexist).

Idempotent ``ADD COLUMN IF NOT EXISTS`` only — no destructive DDL. The
SQL changelog ``20260818/03_builtin_sample_tasks.sql`` stays the
equivalent psql path; fresh databases that created the tables via ORM
metadata before this revision converge through the same ALTERs.

@author qingfeng
"""
from __future__ import annotations

from alembic import op

revision = "0011_builtin_sample_tasks"
down_revision = "0010_workforce_team_runs"
branch_labels = None
depends_on = None

_COLUMN_DDLS = (
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS sample_tasks JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS showcase JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS sample_tasks JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS showcase JSONB NOT NULL DEFAULT '[]'",
)


def upgrade() -> None:
    # 幂等加列（ORM 元数据建出的新库与本迁移收敛到同一形态）
    for ddl in _COLUMN_DDLS:
        op.execute(ddl)


def downgrade() -> None:
    # 降级仅移除运营位展示列（业务数据不受影响）
    op.execute("ALTER TABLE expert_teams DROP COLUMN IF EXISTS showcase")
    op.execute("ALTER TABLE expert_teams DROP COLUMN IF EXISTS sample_tasks")
    op.execute("ALTER TABLE experts DROP COLUMN IF EXISTS showcase")
    op.execute("ALTER TABLE experts DROP COLUMN IF EXISTS sample_tasks")
