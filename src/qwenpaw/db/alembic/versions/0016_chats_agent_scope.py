# -*- coding: utf-8 -*-
"""Chats/session_states agent scoping (数字员工会话隔离).

Revision ID: 0016_chats_agent_scope
Revises: 0015_audit_events
Create Date: 2026-09-09

给 ``chats`` 与 ``session_states`` 补上 ``agent_id`` 维度：JSON 后端时代
每个 agent workspace 独立 ``chats.json``/sessions 目录天然隔离；切到 PG
后端后所有员工共表，缺 agent 维度导致 ``list_chats`` 全租户泄漏（详情页
聊天面板显示其他员工的会话）。存量行归属由
``python -m qwenpaw.db.backfill_chat_agent`` 清洗（psql twin:
changelog 20260909/03）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0016_chats_agent_scope"
down_revision = "0015_audit_events"
branch_labels = None
depends_on = None

_DDLS = (
    # chats：agent 维度列 + 复合索引（既有行先归 default，由清洗脚本修正）
    """
    ALTER TABLE chats ADD COLUMN IF NOT EXISTS agent_id
    VARCHAR(128) NOT NULL DEFAULT 'default'
    """,
    "CREATE INDEX IF NOT EXISTS ix_chats_tenant_agent "
    "ON chats (tenant_id, agent_id)",
    # session_states：PK 扩展为含 agent_id（同用户同 session_id 不再跨员工互覆）
    """
    ALTER TABLE session_states ADD COLUMN IF NOT EXISTS agent_id
    VARCHAR(128) NOT NULL DEFAULT 'default'
    """,
    "ALTER TABLE session_states DROP CONSTRAINT IF EXISTS pk_session_states",
    """
    ALTER TABLE session_states ADD CONSTRAINT pk_session_states
    PRIMARY KEY (tenant_id, agent_id, channel, owner_id, session_id)
    """,
)

_COMMENTS = (
    "COMMENT ON COLUMN chats.agent_id IS "
    "'归属智能体标识（数字员工会话隔离；历史行由 backfill_chat_agent 修正）'",
    "COMMENT ON COLUMN session_states.agent_id IS "
    "'归属智能体标识（数字员工会话状态隔离）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/03 的等价 alembic 路径）
    for ddl in _DDLS:
        op.execute(ddl)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 收缩回旧 PK：先清掉非 default 归属（downgrade 是破坏性操作，保守处理）
    op.execute("DELETE FROM session_states WHERE agent_id <> 'default'")
    op.execute(
        "ALTER TABLE session_states DROP CONSTRAINT IF EXISTS pk_session_states"
    )
    op.execute(
        "ALTER TABLE session_states ADD CONSTRAINT pk_session_states "
        "PRIMARY KEY (tenant_id, channel, owner_id, session_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_chats_tenant_agent")
    op.execute("ALTER TABLE chats DROP COLUMN IF EXISTS agent_id")
    op.execute("ALTER TABLE session_states DROP COLUMN IF EXISTS agent_id")
