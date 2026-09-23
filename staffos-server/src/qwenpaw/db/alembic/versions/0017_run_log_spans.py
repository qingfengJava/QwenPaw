# -*- coding: utf-8 -*-
"""Agent run spans: PG-backed run-log list + execution span tree (运行日志 Span 化).

Revision ID: 0017_run_log_spans
Revises: 0016_chats_agent_scope
Create Date: 2026-09-09

运行日志从「会话消息快照（inbox_trace events）+ JSONL 列表索引」升级为
span 级执行树：``agent_runs`` 承接列表（替代 run_logs/index-*.jsonl），
``agent_run_spans`` 由 SpanRecorderMiddleware 在 AgentScope middleware
边界（on_system_prompt/on_model_call/on_acting/on_reply）采集。无 PG
部署继续走文件路径，不受影响（psql twin: changelog 20260909/04）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0017_run_log_spans"
down_revision = "0016_chats_agent_scope"
branch_labels = None
depends_on = None

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS agent_runs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    run_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    display_name VARCHAR(128),
    session_id VARCHAR(128),
    root_session_id VARCHAR(128),
    chat_id VARCHAR(128),
    user_id VARCHAR(128),
    channel VARCHAR(64),
    source VARCHAR(32),
    environment VARCHAR(16),
    query_preview TEXT,
    status VARCHAR(16) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms INTEGER,
    total_tokens INTEGER,
    model VARCHAR(128),
    version VARCHAR(64),
    app_version VARCHAR(64),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_runs PRIMARY KEY (run_id)
)
"""

_CREATE_SPANS = """
CREATE TABLE IF NOT EXISTS agent_run_spans (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    run_id VARCHAR(64) NOT NULL,
    span_id VARCHAR(64) NOT NULL,
    parent_span_id VARCHAR(64),
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(128),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER,
    input JSONB,
    output JSONB,
    tokens INTEGER,
    status VARCHAR(16),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_started "
    "ON agent_runs (tenant_id, agent_id, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_run_spans_run "
    "ON agent_run_spans (run_id)",
)

_COMMENTS = (
    "COMMENT ON TABLE agent_runs IS "
    "'Agent 运行日志列表行（替代 run_logs/index-*.jsonl 文件索引）'",
    "COMMENT ON COLUMN agent_runs.status IS '状态: running, success, failed'",
    "COMMENT ON COLUMN agent_runs.display_name IS "
    "'智能体可读名称（AgentProfileConfig.name，展示用；空则前端回退 agent_id）'",
    "COMMENT ON TABLE agent_run_spans IS "
    "'Agent 运行执行 span（system/llm/tool/reply，parent_span_id 组树）'",
    "COMMENT ON COLUMN agent_run_spans.kind IS "
    "'span 类型: system, llm, tool, reply'",
)


# Idempotent column backfill for databases already migrated by the
# initial 0017 revision (fresh deployments get the column from CREATE).
_BACKFILL_DDLS = (
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS display_name VARCHAR(128)",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260909/04 的等价 alembic 路径）
    op.execute(_CREATE_RUNS)
    op.execute(_CREATE_SPANS)
    for ddl in _INDEXES:
        op.execute(ddl)
    for ddl in _BACKFILL_DDLS:
        op.execute(ddl)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 清理顺序：先子表 spans 再主表 runs
    op.execute("DROP INDEX IF EXISTS ix_agent_run_spans_run")
    op.execute("DROP TABLE IF EXISTS agent_run_spans")
    op.execute("DROP INDEX IF EXISTS ix_agent_runs_agent_started")
    op.execute("DROP TABLE IF EXISTS agent_runs")
