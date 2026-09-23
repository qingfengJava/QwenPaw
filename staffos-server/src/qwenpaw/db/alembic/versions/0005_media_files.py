# -*- coding: utf-8 -*-
"""Console chat media uploads persisted to PostgreSQL.

Revision ID: 0005_media_files
Revises: 0004_table_timestamps
Create Date: 2026-08-16

Adds the ``media_files`` table: the durable database copy of every file
uploaded through ``POST /api/console/upload``. The workspace-local
``media/`` file stays the working copy for agent tooling; this table
backs the ``GET /api/console/media/{stored_name}`` recall endpoint so
chat image preview survives local cleanup.

Idempotent (``checkfirst``), matching the 0002-0004 rollout philosophy.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_media  # noqa: F401  (register tables)

revision = "0005_media_files"
down_revision = "0004_table_timestamps"
branch_labels = None
depends_on = None

_TABLES = ("media_files",)


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    for name in reversed(_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
