# -*- coding: utf-8 -*-
"""XianWork share links.

Revision ID: 0008_xian_shares
Revises: 0007_media_registry
Create Date: 2026-08-17

Adds the ``xian_shares`` table: one capability-token share per chat.
The token is the secret — anyone holding it can read the shared chat
transcript + registered files via the public view endpoint, without
login. Ownership backstop (RLS ``owner_isolation``) is applied by the
SQL snapshots (changelog/20260817/01_xian_shares.sql → test.sql /
prod.sql), matching the xian_workspaces rollout philosophy.

Idempotent (``checkfirst``), matching the 0002-0006 rollout philosophy.
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_shares  # noqa: F401  (register tables)

revision = "0008_xian_shares"
down_revision = "0007_media_registry"
branch_labels = None
depends_on = None

_TABLES = ("xian_shares",)


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    for name in reversed(_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
