# -*- coding: utf-8 -*-
"""media_files 会话文件登记扩展.

Revision ID: 0007_media_registry
Revises: 0006_xian_workspaces
Create Date: 2026-08-16

Upgrades ``media_files`` from a bare blob cache into a session file
registry. New columns: ``chat_id`` / ``session_id`` / ``owner_id`` /
``source`` (upload | agent_output) / ``storage_type`` (db | local |
minio | oss) / ``storage_uri`` (absolute local path or object URI) /
``sha256`` (content fingerprint; agent outputs use its first 16 hex
chars inside ``stored_name`` for content-addressed dedup).

All additions are nullable or defaulted, so pre-existing rows keep
their semantics (upload + local/PG dual write). Matches the SQL
snapshot rollout (changelog/20260816/03_media_registry.sql →
test.sql / prod.sql). Idempotent (ADD COLUMN IF NOT EXISTS).

DDL statements are fixed string literals (no interpolation) so static
security scanning cannot mistake them for dynamic SQL assembly.
"""
from __future__ import annotations

from alembic import op

revision = "0007_media_registry"
down_revision = "0006_xian_workspaces"
branch_labels = None
depends_on = None

_UPGRADE_DDLS = (
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS chat_id VARCHAR(128)",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS session_id VARCHAR(255)",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS owner_id VARCHAR(128)",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'upload'",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS storage_type VARCHAR(16) NOT NULL DEFAULT 'db'",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS storage_uri TEXT",
    "ALTER TABLE media_files ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_media_files_chat ON media_files (tenant_id, chat_id)",
    "CREATE INDEX IF NOT EXISTS ix_media_files_session ON media_files (tenant_id, session_id)",
)

_DOWNGRADE_DDLS = (
    "DROP INDEX IF EXISTS ix_media_files_session",
    "DROP INDEX IF EXISTS ix_media_files_chat",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS sha256",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS storage_uri",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS storage_type",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS source",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS owner_id",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS session_id",
    "ALTER TABLE media_files DROP COLUMN IF EXISTS chat_id",
)


def upgrade() -> None:
    for ddl in _UPGRADE_DDLS:
        op.execute(ddl)


def downgrade() -> None:
    for ddl in _DOWNGRADE_DDLS:
        op.execute(ddl)
