# -*- coding: utf-8 -*-
"""Team draft_revision column (CAS optimistic lock for team drafts).

Revision ID: 0053_team_draft_revision
Revises: 0052_team_run_active_seconds
Create Date: 2026-09-22

P5 变更提案闭环前置列：

- ``expert_teams.draft_revision``：草稿修订号，每次 PATCH 成功递增，
  发布不重置。客户端携带 expected_revision 做 CAS 校验，冲突返回
  409；AI 变更提案（team_change_requests.base_revision）以此为
  批准绑定基准。

幂等 DDL。（psql twin: changelog 20260922/02_team_draft_revision.sql）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0053_team_draft_revision"
down_revision = "0052_team_run_active_seconds"
branch_labels = None
depends_on = None

_ALTER = (
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS draft_revision "
    "INTEGER NOT NULL DEFAULT 0"
)

_COMMENT = (
    "COMMENT ON COLUMN expert_teams.draft_revision IS "
    "'草稿修订号: 每次 PATCH 成功递增, 发布不重置; 客户端携带 "
    "expected_revision 做 CAS 校验, 冲突返回 409'"
)


def upgrade() -> None:
    # 补列（幂等）
    op.execute(_ALTER)
    # 注释
    op.execute(_COMMENT)


def downgrade() -> None:
    op.execute("ALTER TABLE expert_teams DROP COLUMN IF EXISTS draft_revision")
