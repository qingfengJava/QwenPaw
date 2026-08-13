# -*- coding: utf-8 -*-
"""Initial schema: chats / session_states / history_entries + RLS.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13

Creates the three M2 storage tables from the SQLAlchemy metadata (idempotent
``CREATE TABLE IF NOT EXISTS`` via checkfirst), adds the generated
``tsvector`` column + GIN index replacing the SQLite FTS5 index, and
enables PERMISSIVE owner-isolation RLS policies on every user-data table.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models  # noqa: F401  (register tables on metadata)
from qwenpaw.db.rls import RLS_TABLES, policy_statements

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = ("chats", "session_states", "history_entries")


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)

    # tsvector replacing the file-era SQLite FTS5 index. 'simple' config:
    # language-agnostic tokenization (porter stemming would mangle CJK).
    op.execute(
        """
        ALTER TABLE history_entries
            ADD COLUMN IF NOT EXISTS tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(content, ''))
            ) STORED
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_history_tsv
            ON history_entries USING GIN (tsv)
        """,
    )

    for table in RLS_TABLES:
        for statement in policy_statements(table):
            op.execute(statement)


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS owner_isolation ON {table}")
    op.execute("DROP INDEX IF EXISTS ix_history_tsv")
    op.execute("ALTER TABLE history_entries DROP COLUMN IF EXISTS tsv")
    for name in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
