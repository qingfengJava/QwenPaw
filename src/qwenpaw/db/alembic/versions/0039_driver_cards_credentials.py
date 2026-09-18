# -*- coding: utf-8 -*-
"""MCP/ACP driver cards + credentials PG authoritative plane.

Revision ID: 0039_driver_cards_credentials
Revises: 0038_agent_documents_owner_draft
Create Date: 2026-09-18

T12 driver PG 权威（数字员工外部能力配置）：

- ``driver_cards``：驱动卡（MCP/ACP）权威表，自然键
  ``(tenant, agent, protocol, name)``；``enabled`` 独立列，``spec`` JSONB
  承载 endpoint/config/credentials（alias→{kind,ref}），``policy`` JSONB
  承载 DriverPolicy（默认效应 + 规则数组）；
- ``driver_credentials``：驱动凭据密文表，自然键 ``(tenant, agent, ref)``；
  ``cipher`` 存放经 secret_store（Fernet）加密后的凭据 JSON，明文不落库。

后端语义与档案/技能平面一致：``QWENPAW_STORAGE_BACKEND`` 为 ``json``
（默认，无 PG）时两表零动作，驱动卡仍走 workspace 文件平面；``dual``/``pg``
时以本两表为权威源，文件降级为写穿投影 + 启动一次性回填
（见 ``app/driver_config/pg_store.py`` 与 ``driver_config_service``）。

全部 DDL 幂等（CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS）。
（psql twin: changelog 20260918/02，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0039_driver_cards_credentials"
down_revision = "0038_agent_documents_owner_draft"
branch_labels = None
depends_on = None

_CREATE_DRIVER_CARDS = """
CREATE TABLE IF NOT EXISTS driver_cards (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    protocol VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    spec JSONB NOT NULL DEFAULT '{}',
    policy JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_cards
        PRIMARY KEY (tenant_id, agent_id, protocol, name)
)
"""

_CREATE_DRIVER_CREDENTIALS = """
CREATE TABLE IF NOT EXISTS driver_credentials (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    cipher TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_credentials
        PRIMARY KEY (tenant_id, agent_id, ref)
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_driver_cards_agent "
    "ON driver_cards (tenant_id, agent_id)",
    "CREATE INDEX IF NOT EXISTS ix_driver_credentials_agent "
    "ON driver_credentials (tenant_id, agent_id)",
)

_COMMENTS = (
    "COMMENT ON TABLE driver_cards IS "
    "'MCP/ACP 驱动卡权威表（数字员工外部能力配置：endpoint/config/凭据引用/"
    "访问策略；json 后端零动作、pg/dual 权威，文件降级为写穿投影 + 启动回填）'",
    "COMMENT ON COLUMN driver_cards.spec IS "
    "'驱动卡主体 JSONB（endpoint/config/credentials：alias→{kind,ref}；"
    "凭据密文另存 driver_credentials）'",
    "COMMENT ON COLUMN driver_cards.policy IS "
    "'访问策略 JSONB（DriverPolicy：default_effect + rules 数组）'",
    "COMMENT ON TABLE driver_credentials IS "
    "'驱动凭据密文表（secret_store/Fernet 加密后的凭据 JSON：kind/public/"
    "secrets/meta；明文绝不落库，cipher 为空表示无密文）'",
    "COMMENT ON COLUMN driver_credentials.ref IS "
    "'凭据引用（与 DriverCard.credentials 的 ref 对应，env: 前缀引用不落库）'",
    "COMMENT ON COLUMN driver_credentials.cipher IS "
    "'凭据密文（secret_store.encrypt 后的 JSON，带 ENC: 前缀；读取时 "
    "decrypt 还原）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260918/02 的等价 alembic 路径）
    op.execute(_CREATE_DRIVER_CARDS)
    op.execute(_CREATE_DRIVER_CREDENTIALS)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_driver_credentials_agent")
    op.execute("DROP INDEX IF EXISTS ix_driver_cards_agent")
    op.execute("DROP TABLE IF EXISTS driver_credentials")
    op.execute("DROP TABLE IF EXISTS driver_cards")
