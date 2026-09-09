# -*- coding: utf-8 -*-
"""Provider models row-level plane (one row per configured model).

Revision ID: 0019_provider_models
Revises: 0018_provider_config_plane
Create Date: 2026-09-09

行级模型表 ``provider_models``：每个厂商下用户配置的每个模型一行，
参数（generate_kwargs / config_overrides / thinking 等）独立存于
``config`` JSONB，常用能力提升为列便于查询。``provider_configs.snapshot``
仍是内存重建的权威快照（与文件平面逐字节一致）；本表是每次配置变更时
自动投影同步的规范化落地，供人工查询 / BI / 未来行级关联使用
（psql twin: changelog 20260909/06）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0019_provider_models"
down_revision = "0018_provider_config_plane"
branch_labels = None
depends_on = None

_CREATE_PROVIDER_MODELS = """
CREATE TABLE IF NOT EXISTS provider_models (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    model_id VARCHAR(128) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    source VARCHAR(16) NOT NULL DEFAULT 'builtin',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_free BOOLEAN NOT NULL DEFAULT FALSE,
    supports_multimodal BOOLEAN,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_models
        PRIMARY KEY (tenant_id, provider_id, model_id)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE provider_models IS "
    "'供应商模型行级表（每厂商每模型一行，参数独立；"
    "由 provider_configs.snapshot 每次变更自动投影同步）'",
    "COMMENT ON COLUMN provider_models.model_id IS "
    "'模型 ID（如 qwen3.7-max）'",
    "COMMENT ON COLUMN provider_models.source IS "
    "'模型来源: builtin(内置目录), user(用户添加), discovered(自动发现)'",
    "COMMENT ON COLUMN provider_models.enabled IS "
    "'启用开关（false=已禁用：保留配置但从所有选择器隐藏）'",
    "COMMENT ON COLUMN provider_models.config IS "
    "'模型级参数（generate_kwargs/config_overrides/thinking/"
    "max_input_length 等全部其余字段）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/06 的等价 alembic 路径）
    op.execute(_CREATE_PROVIDER_MODELS)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS provider_models")
