# -*- coding: utf-8 -*-
"""XianWork user workspace registry.

Revision ID: 0006_xian_workspaces
Revises: 0005_media_files
Create Date: 2026-08-16

Adds the ``xian_workspaces`` table: the registry of disk directories a
user has claimed as workspaces. Chat binding reuses the existing
``chats.meta.runtime_context.project_dir`` mechanism, so this table only
maps directory → display name and never touches the ``chats`` schema.
RLS owner isolation is applied by the SQL snapshots
(changelog/20260816/02_xian_workspaces.sql → test.sql/prod.sql), matching
the media_files rollout philosophy.

Idempotent (``checkfirst``), matching the 0002-0005 rollout philosophy.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_workspaces  # noqa: F401  (register tables)

revision = "0006_xian_workspaces"
down_revision = "0005_media_files"
branch_labels = None
depends_on = None

_TABLES = ("xian_workspaces",)


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    for name in reversed(_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
