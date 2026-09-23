# -*- coding: utf-8 -*-
"""Agent default model slots (per-agent LLM slot plane).

Revision ID: 0020_agent_model_slots
Revises: 0019_provider_models
Create Date: 2026-09-09

数字员工默认模型槽位表 ``agent_model_slots``：后台档案区为每个员工
配置的默认运行模型（agent.json ``active_model`` 的 PG 落库平面），
列结构与 ``model_active_slots`` 完全对齐并增加 ``agent_id`` 维度。
``QWENPAW_STORAGE_BACKEND`` 为 ``json``（默认）时不参与任何读写路径，
``dual`` 影子双写，``pg`` 权威读；运行时解析优先级：本表 →
agent.json → 全局 ``model_active_slots``（psql twin: changelog
20260909/07，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0020_agent_model_slots"
down_revision = "0019_provider_models"
branch_labels = None
depends_on = None

_CREATE_AGENT_MODEL_SLOTS = """
CREATE TABLE IF NOT EXISTS agent_model_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    slot_name VARCHAR(32) NOT NULL DEFAULT 'llm',
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_model_slots
        PRIMARY KEY (tenant_id, agent_id, slot_name)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE agent_model_slots IS "
    "'数字员工默认模型槽位表（后台档案区为每个员工配置的默认运行模型；"
    "agent.json active_model 的 PG 落库平面，运行时解析优先级：本表 → "
    "agent.json → 全局 active_llm）'",
    "COMMENT ON COLUMN agent_model_slots.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN agent_model_slots.agent_id IS "
    "'数字员工 ID（智能体档案 ID，如 python-fullstack）'",
    "COMMENT ON COLUMN agent_model_slots.slot_name IS "
    "'槽位名: llm（预留 embedding 等槽位）'",
    "COMMENT ON COLUMN agent_model_slots.provider_id IS "
    "'模型提供商 ID（如 aliyun-codingplan；空串视为未配置，"
    "解析时跳过本表回退 agent.json）'",
    "COMMENT ON COLUMN agent_model_slots.model IS "
    "'模型 ID（如 GLM-5.3-Flash；空串视为未配置）'",
    "COMMENT ON COLUMN agent_model_slots.created_at IS "
    "'创建时间（首次配置默认模型时写入）'",
    "COMMENT ON COLUMN agent_model_slots.updated_at IS "
    "'更新时间（每次切换默认模型时刷新）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/01 的等价 alembic 路径）
    op.execute(_CREATE_AGENT_MODEL_SLOTS)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_model_slots")
