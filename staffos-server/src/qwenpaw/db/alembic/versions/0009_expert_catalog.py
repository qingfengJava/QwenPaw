# -*- coding: utf-8 -*-
"""Expert catalog plane: market columns, skill bindings, team reserves.

Revision ID: 0009_expert_catalog
Revises: 0008_xian_shares
Create Date: 2026-08-18

Upgrades the expert publishing plane into a marketplace:

- ``experts`` gains catalog columns (``owner_id`` / ``visibility`` /
  ``is_builtin`` / ``title`` / ``category`` / ``badge`` / ``tags`` /
  ``system_prompt`` / ``usage_count`` / ``featured``) plus the
  ``ix_experts_market`` / ``ix_experts_owner`` indexes;
- new ``expert_skills`` table binds shared-registry skills to experts
  (created via metadata ``checkfirst`` so fresh databases get it from
  ``0002_enterprise`` — the ALTERs below are then no-ops, matching the
  0002-0008 rollout philosophy);
- ``expert_teams`` gains ``owner_id`` / ``category`` / ``tags`` /
  ``orchestration`` (reserved for the runtime orchestrator) and
  ``expert_team_members`` gains ``member_role`` (lead / member).

All additions are nullable or defaulted, so pre-existing rows keep
their semantics (admin-created, org-visible, no skills). Matches the
SQL snapshot rollout (changelog/20260818/01_expert_catalog.sql →
test.sql / prod.sql). Idempotent (ADD COLUMN IF NOT EXISTS).

DDL statements are fixed string literals (no interpolation) so static
security scanning cannot mistake them for dynamic SQL assembly.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_enterprise  # noqa: F401  (register tables)

revision = "0009_expert_catalog"
down_revision = "0008_xian_shares"
branch_labels = None
depends_on = None

_NEW_TABLES = ("expert_skills",)

_UPGRADE_DDLS = (
    # --- experts: catalog columns ------------------------------------
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'org'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS is_builtin BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS badge TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS system_prompt TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS usage_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS featured BOOLEAN NOT NULL DEFAULT FALSE",
    # --- expert_teams: catalog + orchestration reserves ---------------
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS owner_id TEXT",
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'",
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS orchestration JSONB NOT NULL DEFAULT '{}'",
    # --- expert_team_members: member role -----------------------------
    "ALTER TABLE expert_team_members ADD COLUMN IF NOT EXISTS member_role TEXT NOT NULL DEFAULT 'member'",
    # --- market / ownership indexes -----------------------------------
    "CREATE INDEX IF NOT EXISTS ix_experts_market ON experts (tenant_id, status, category, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_experts_owner ON experts (tenant_id, owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_expert_skills_expert ON expert_skills (tenant_id, expert_id)",
)

_DOWNGRADE_DDLS = (
    "DROP INDEX IF EXISTS ix_expert_skills_expert",
    "DROP INDEX IF EXISTS ix_experts_owner",
    "DROP INDEX IF EXISTS ix_experts_market",
    "ALTER TABLE expert_team_members DROP COLUMN IF EXISTS member_role",
    "ALTER TABLE expert_teams DROP COLUMN IF EXISTS orchestration",
    "ALTER TABLE expert_teams DROP COLUMN IF EXISTS tags",
    "ALTER TABLE expert_teams DROP COLUMN IF EXISTS category",
    "ALTER TABLE expert_teams DROP COLUMN IF EXISTS owner_id",
    "ALTER TABLE experts DROP COLUMN IF EXISTS featured",
    "ALTER TABLE experts DROP COLUMN IF EXISTS usage_count",
    "ALTER TABLE experts DROP COLUMN IF EXISTS system_prompt",
    "ALTER TABLE experts DROP COLUMN IF EXISTS tags",
    "ALTER TABLE experts DROP COLUMN IF EXISTS badge",
    "ALTER TABLE experts DROP COLUMN IF EXISTS category",
    "ALTER TABLE experts DROP COLUMN IF EXISTS title",
    "ALTER TABLE experts DROP COLUMN IF EXISTS is_builtin",
    "ALTER TABLE experts DROP COLUMN IF EXISTS visibility",
    "ALTER TABLE experts DROP COLUMN IF EXISTS owner_id",
)


def upgrade() -> None:
    # New tables first: the ix_expert_skills_expert index DDL above
    # requires expert_skills to exist on legacy databases.
    bind = op.get_bind()
    for name in _NEW_TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)
    for ddl in _UPGRADE_DDLS:
        op.execute(ddl)


def downgrade() -> None:
    for ddl in _DOWNGRADE_DDLS:
        op.execute(ddl)
    for name in reversed(_NEW_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
