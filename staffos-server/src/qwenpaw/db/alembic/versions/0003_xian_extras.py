# -*- coding: utf-8 -*-
"""XianWork project extras: instructions column + bindings/automations.

Revision ID: 0003_xian_extras
Revises: 0002_enterprise
Create Date: 2026-08-14

Adds the ``projects.instructions`` text column (project SOP / system
prompt shown in the right config panel) and two collaboration tables:

- ``project_bindings`` — which connectors (MCP clients) / skills a
  project's AI may use (registry stays authoritative elsewhere);
- ``project_automations`` — project-plane projection of scheduled cron
  jobs executed by the project's shared AI agent.

Everything is idempotent (``checkfirst`` / ``IF NOT EXISTS``), matching
the 0002 rollout philosophy.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_enterprise  # noqa: F401  (register tables)

revision = "0003_xian_extras"
down_revision = "0002_enterprise"
branch_labels = None
depends_on = None

_TABLES = (
    "project_bindings",
    "project_automations",
)


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)

    # Project instructions (SOP / system prompt) for pre-0003 databases;
    # fresh installs already get the column from the ProjectRow metadata.
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS instructions TEXT",
    )
    op.execute(
        "UPDATE projects SET instructions = '' WHERE instructions IS NULL",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS instructions")
    for name in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
