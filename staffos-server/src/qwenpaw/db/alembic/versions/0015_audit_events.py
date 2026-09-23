# -*- coding: utf-8 -*-
"""Governance audit events (SQLite retirement).

Revision ID: 0015_audit_events
Revises: 0014_agent_documents
Create Date: 2026-09-09

Adds ``audit_events``: the PostgreSQL replacement for the legacy SQLite
``audit.db`` governance store (psql twin: changelog 20260909/02). ``ts``
keeps the millisecond-since-epoch semantics of the SQLite column so range
queries compare identically after the migration.

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0015_audit_events"
down_revision = "0014_agent_documents"
branch_labels = None
depends_on = None

_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
        id            BIGSERIAL PRIMARY KEY,
        ts            BIGINT NOT NULL,
        workspace_dir TEXT NOT NULL,
        agent_id      TEXT NOT NULL,
        session_id    TEXT NOT NULL,
        tool_name     TEXT NOT NULL,
        target        TEXT NOT NULL,
        decision      VARCHAR(32) NOT NULL,
        reason        TEXT NOT NULL DEFAULT '',
        extra         JSONB,
        actor_id      TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_events_ts "
    "ON audit_events (tenant_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_workspace "
    "ON audit_events (tenant_id, workspace_dir)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_agent "
    "ON audit_events (tenant_id, agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_tool "
    "ON audit_events (tenant_id, tool_name)",
)

_COMMENTS = (
    "COMMENT ON TABLE audit_events IS "
    "'治理审计事件表：每次 assert_policy/audit 调用的 5W 记录"
    "（SQLite audit.db 的 PG 替代；ts 为 UTC 毫秒时间戳）'",
    "COMMENT ON COLUMN audit_events.ts IS '事件时间（UTC 毫秒时间戳）'",
    "COMMENT ON COLUMN audit_events.workspace_dir IS '事件所属工作区路径'",
    "COMMENT ON COLUMN audit_events.agent_id IS '执行调用的智能体标识'",
    "COMMENT ON COLUMN audit_events.session_id IS '调用所属会话标识'",
    "COMMENT ON COLUMN audit_events.tool_name IS '被治理的工具名'",
    "COMMENT ON COLUMN audit_events.target IS '工具调用目标'",
    "COMMENT ON COLUMN audit_events.decision IS "
    "'治理决策: allow-允许, deny-拒绝, ask-询问, sandbox_fallback-沙箱降级'",
    "COMMENT ON COLUMN audit_events.reason IS '决策原因说明'",
    "COMMENT ON COLUMN audit_events.extra IS '扩展信息（JSONB）'",
    "COMMENT ON COLUMN audit_events.actor_id IS "
    "'可信用户身份（M4；匿名调用为空串）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/02 的等价 alembic 路径）
    for ddl in _DDLS:
        op.execute(ddl)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
