# -*- coding: utf-8 -*-
"""Expert API keys (P4 /api/open credential plane).

Revision ID: 0013_expert_api_keys
Revises: 0012_digital_employee_capability
Create Date: 2026-08-30

Adds ``expert_api_keys``: the issue/revoke ledger for expert-scoped
open-API keys (psql twin: changelog 20260830/02). Plaintext keys are
returned once at issue time; only the SHA-256 hash + display prefix are
persisted. ``expert_id`` is the permission boundary; ``revoked_at``
is the soft-revoke marker.

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0013_expert_api_keys"
down_revision = "0012_digital_employee_capability"
branch_labels = None
depends_on = None

_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS expert_api_keys (
        tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
        id          VARCHAR(64) NOT NULL,
        expert_id   VARCHAR(64) NOT NULL,
        name        TEXT NOT NULL DEFAULT '',
        key_hash    TEXT NOT NULL,
        key_prefix  TEXT NOT NULL DEFAULT '',
        created_by  TEXT,
        expires_at  TIMESTAMPTZ,
        revoked_at  TIMESTAMPTZ,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_expert_api_keys PRIMARY KEY (tenant_id, id),
        CONSTRAINT uq_expert_api_keys_hash UNIQUE (tenant_id, key_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_expert_api_keys_expert "
    "ON expert_api_keys (tenant_id, expert_id)",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260830/02 的等价 alembic 路径）
    for ddl in _DDLS:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expert_api_keys")
