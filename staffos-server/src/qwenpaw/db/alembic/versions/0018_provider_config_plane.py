# -*- coding: utf-8 -*-
"""Provider configuration plane: provider_configs + model_active_slots.

Revision ID: 0018_provider_config_plane
Revises: 0017_run_log_spans
Create Date: 2026-09-09

模型配置落库存储平面：``provider_configs`` 承接每个 provider 的整包
快照（extra_models / discovered_models / hidden_model_ids /
removed_model_ids / discovery 状态等，JSONB），api_key 以 Fernet 密文
（``ENC:`` 前缀，主密钥同 secret_store）提升为独立列 ``api_key_encrypted``
便于审计；``enabled`` 列镜像控制台"停用"语义（未配 key 且需要 key 即
停用）。``model_active_slots`` 承接 active_llm 槽位（slot_name 现阶段
固定 ``llm``，为 embedding 等槽位预留）。``QWENPAW_STORAGE_BACKEND``
为 ``json``（默认）时两表不参与任何读写路径（psql twin:
changelog 20260909/05）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0018_provider_config_plane"
down_revision = "0017_run_log_spans"
branch_labels = None
depends_on = None

_CREATE_PROVIDER_CONFIGS = """
CREATE TABLE IF NOT EXISTS provider_configs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    api_key_encrypted TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot JSONB NOT NULL DEFAULT '{}',
    snapshot_schema_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_configs PRIMARY KEY (tenant_id, provider_id)
)
"""

_CREATE_ACTIVE_SLOTS = """
CREATE TABLE IF NOT EXISTS model_active_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    slot_name VARCHAR(32) NOT NULL,
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_model_active_slots PRIMARY KEY (tenant_id, slot_name)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE provider_configs IS "
    "'模型提供商配置落库平面（api_key 以 ENC: 密文存储，"
    "snapshot 为整包 provider 快照 JSONB）'",
    "COMMENT ON COLUMN provider_configs.api_key_encrypted IS "
    "'Fernet 加密后的 API Key（ENC: 前缀，主密钥见 secret_store）'",
    "COMMENT ON COLUMN provider_configs.enabled IS "
    "'厂商启用状态（镜像控制台语义：需要 key 且未配置即停用）'",
    "COMMENT ON COLUMN provider_configs.snapshot IS "
    "'整包 provider 快照（extra_models/discovered_models/"
    "hidden_model_ids/removed_model_ids 等，不含 api_key 明文）'",
    "COMMENT ON TABLE model_active_slots IS "
    "'模型槽位表（承接 active_llm；slot_name 现阶段固定 llm）'",
    "COMMENT ON COLUMN model_active_slots.slot_name IS "
    "'槽位名: llm（预留 embedding 等）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/05 的等价 alembic 路径）
    op.execute(_CREATE_PROVIDER_CONFIGS)
    op.execute(_CREATE_ACTIVE_SLOTS)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 清理顺序：先槽位表再配置表
    op.execute("DROP TABLE IF EXISTS model_active_slots")
    op.execute("DROP TABLE IF EXISTS provider_configs")
