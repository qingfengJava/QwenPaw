# -*- coding: utf-8 -*-
"""Agent model slot parameter overrides + per-model profiles.

Revision ID: 0021_agent_model_slot_overrides
Revises: 0020_agent_model_slots
Create Date: 2026-09-10

``agent_model_slots`` 档案化改造：

1. 增加 ``config`` JSONB 列：模型参数覆盖（上下文窗口 / 思考开关 /
   思考预算 / 推理努力档位），None 字段语义为"跟随全局基线"；
2. 主键扩展到模型维度：一行 = 员工用过的某模型的参数档案，
   参数跟模型走（切走再切回自动恢复该模型的历史参数）；
3. 增加 ``is_active`` 激活位 + 偏唯一索引：同一员工同一槽位
   至多一行激活，切换模型即切换激活档案。

本迁移幂等，兼容两条升级路径：全新库（0020 建表后首次执行）
与已应用旧版 0021 的存量库（仅含每员工一行数据，平移为激活档案）。
psql twin: changelog 20260910/01，分支 agent_run_logs_20260908。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0021_agent_model_slot_overrides"
down_revision = "0020_agent_model_slots"
branch_labels = None
depends_on = None

_ADD_CONFIG_COLUMN = """
ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS config JSONB
"""

_COMMENT_CONFIG = (
    "COMMENT ON COLUMN agent_model_slots.config IS "
    "'模型参数档案 JSONB（max_input_length/thinking_enabled/"
    "thinking_budget/reasoning_effort；NULL 或字段缺省=跟随全局基线；"
    "归属该行的 provider_id+model）'"
)

_COMMENT_IS_ACTIVE = (
    "COMMENT ON COLUMN agent_model_slots.is_active IS "
    "'激活状态位：当前生效的模型档案；同一员工同一槽位至多一行 TRUE'"
)

# asyncpg 不支持多语句批量执行，逐条拆分（幂等）
_UPGRADE_PROFILE_STEPS = (
    "ALTER TABLE agent_model_slots "
    "DROP CONSTRAINT IF EXISTS pk_agent_model_slots",
    "ALTER TABLE agent_model_slots "
    "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE",
    "UPDATE agent_model_slots SET is_active = TRUE WHERE NOT is_active",
    "ALTER TABLE agent_model_slots "
    "ADD CONSTRAINT pk_agent_model_slots "
    "PRIMARY KEY (tenant_id, agent_id, slot_name, provider_id, model)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_model_slots_active "
    "ON agent_model_slots (tenant_id, agent_id, slot_name) WHERE is_active",
)

_DOWNGRADE_PROFILE_STEPS = (
    "DROP INDEX IF EXISTS uq_agent_model_slots_active",
    # 去重还原每员工一行（同一槽位仅保留最旧行）；
    # 不依赖 is_active，兼容从未应用档案化的旧存量库
    "DELETE FROM agent_model_slots a USING agent_model_slots b "
    "WHERE a.tenant_id = b.tenant_id AND a.agent_id = b.agent_id "
    "AND a.slot_name = b.slot_name AND a.ctid > b.ctid",
    "ALTER TABLE agent_model_slots "
    "DROP CONSTRAINT IF EXISTS pk_agent_model_slots",
    "ALTER TABLE agent_model_slots "
    "ADD CONSTRAINT pk_agent_model_slots "
    "PRIMARY KEY (tenant_id, agent_id, slot_name)",
    "ALTER TABLE agent_model_slots DROP COLUMN IF EXISTS is_active",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260910/01 的等价 alembic 路径）
    op.execute(_ADD_CONFIG_COLUMN)
    op.execute(_COMMENT_CONFIG)
    # 档案化：主键加模型维度 + is_active 激活位 + 唯一激活索引
    for step in _UPGRADE_PROFILE_STEPS:
        op.execute(step)
    op.execute(_COMMENT_IS_ACTIVE)


def downgrade() -> None:
    # 还原为每员工一行（仅保留激活档案），再移除档案化结构
    for step in _DOWNGRADE_PROFILE_STEPS:
        op.execute(step)
    op.execute("ALTER TABLE agent_model_slots DROP COLUMN IF EXISTS config")
