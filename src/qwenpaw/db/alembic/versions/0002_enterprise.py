# -*- coding: utf-8 -*-
"""XianWork enterprise schema: org/project/task/feed/expert tables.

Revision ID: 0002_enterprise
Revises: 0001_initial
Create Date: 2026-08-14

Creates the eleven enterprise tables from the SQLAlchemy metadata
(idempotent ``CREATE TABLE IF NOT EXISTS`` via checkfirst), adds the
``chats.project_id`` column + supporting indexes for existing databases,
and keeps everything tenant-scoped via ``TenantMixin``. Application-layer
filtering remains the primary isolation enforcer (no new RLS policies in
this revision — mirrors the PERMISSIVE rollout philosophy of 0001).
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_enterprise  # noqa: F401  (register tables)

revision = "0002_enterprise"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLES = (
    "orgs",
    "departments",
    "department_members",
    "projects",
    "project_members",
    "tasks",
    "feed_events",
    "experts",
    "expert_teams",
    "expert_team_members",
    "published_experts",
    "token_usage_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)

    # chats.project_id for pre-0002 databases (fresh installs already get
    # the column + indexes from the ChatRow metadata above).
    op.execute("ALTER TABLE chats ADD COLUMN IF NOT EXISTS project_id TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_project"
        " ON chats (tenant_id, project_id)",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chats_owner_updated"
        " ON chats (tenant_id, owner_id, updated_at)",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chats_owner_updated")
    op.execute("DROP INDEX IF EXISTS ix_chats_project")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS project_id")
    for name in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
