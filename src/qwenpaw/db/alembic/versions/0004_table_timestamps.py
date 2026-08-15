# -*- coding: utf-8 -*-
"""Table timestamp discipline: created_at/updated_at on every enterprise table.

Revision ID: 0004_table_timestamps
Revises: 0003_xian_extras
Create Date: 2026-08-15

Project SQL standard: every business table carries a primary key plus
DB-maintained ``created_at`` / ``updated_at``. Four enterprise tables were
created without the full pair (append-only / snapshot semantics made the
timestamps look optional at 0002/0003 time):

- ``expert_team_members`` — had neither;
- ``published_experts`` — had ``published_at`` only;
- ``feed_events`` / ``token_usage_events`` — had ``created_at`` only.

The models now inherit ``TimestampMixin`` (class-level ``created_at``
definitions still win where present), and this revision backfills the
missing columns for pre-0004 databases with an instant ``ADD COLUMN ...
NOT NULL DEFAULT now()``. Append-only tables never UPDATE, so their
``updated_at`` simply stays at the insertion instant.
"""
from __future__ import annotations

from alembic import op

revision = "0004_table_timestamps"
down_revision = "0003_xian_extras"
branch_labels = None
depends_on = None

_COLUMNS: dict[str, tuple[str, ...]] = {
    "expert_team_members": ("created_at", "updated_at"),
    "published_experts": ("created_at", "updated_at"),
    "feed_events": ("updated_at",),
    "token_usage_events": ("updated_at",),
}


def upgrade() -> None:
    for table, columns in _COLUMNS.items():
        for column in columns:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
            )


def downgrade() -> None:
    for table, columns in _COLUMNS.items():
        for column in columns:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
