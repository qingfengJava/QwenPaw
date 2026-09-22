# -*- coding: utf-8 -*-
"""Team run contracts ledger: revisions / attempts / events / budget.

Revision ID: 0050_team_run_contracts_ledger
Revises: 0049_team_config_versions
Create Date: 2026-09-21

专家团职责协作 T2（运行修订、尝试、事件与预算底座）：

- ``team_run_revisions``：requirement/plan/context 修订留痕（重规划
  不删除历史，旧图进入 payload）；
- ``team_run_attempts``：每次真实执行尝试（先落库后启动成员；
  usage_reported=False 表示消耗未知）；
- ``team_run_events``：全部 run 的有序持久事件（无项目 run 也可回放）；
- ``team_run_budget_reservations``：调用前原子预留/结算/释放，防止
  并发"各自看余额"超售。

审批记录与产物本体仍复用既有系统；本迁移只承载团队运行账本。
全部 DDL 幂等。（psql twin: changelog 20260921/02）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0050_team_run_contracts_ledger"
down_revision = "0049_team_config_versions"
branch_labels = None
depends_on = None

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS team_run_revisions (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        run_id VARCHAR(64) NOT NULL,
        kind VARCHAR(16) NOT NULL,
        revision INTEGER NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_team_run_revisions
            PRIMARY KEY (tenant_id, run_id, kind, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_run_attempts (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        run_id VARCHAR(64) NOT NULL,
        node_key VARCHAR(128) NOT NULL DEFAULT '',
        attempt INTEGER NOT NULL DEFAULT 1,
        expert_id VARCHAR(64) NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'started',
        usage_reported BOOLEAN NOT NULL DEFAULT false,
        token_cost INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_team_run_attempts PRIMARY KEY (tenant_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_run_events (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        run_id VARCHAR(64) NOT NULL,
        seq INTEGER NOT NULL,
        kind VARCHAR(48) NOT NULL,
        actor TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_team_run_events PRIMARY KEY (tenant_id, run_id, seq)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_run_budget_reservations (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        run_id VARCHAR(64) NOT NULL,
        node_key VARCHAR(128) NOT NULL DEFAULT '',
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        reserved_tokens INTEGER NOT NULL DEFAULT 0,
        used_tokens INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_team_run_budget_resv PRIMARY KEY (tenant_id, id)
    )
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_team_run_revisions_run "
    "ON team_run_revisions (tenant_id, run_id)",
    "CREATE INDEX IF NOT EXISTS ix_team_run_attempts_node "
    "ON team_run_attempts (tenant_id, run_id, node_key)",
    "CREATE INDEX IF NOT EXISTS ix_team_run_events_seq "
    "ON team_run_events (tenant_id, run_id, seq)",
    "CREATE INDEX IF NOT EXISTS ix_team_run_budget_resv_run "
    "ON team_run_budget_reservations (tenant_id, run_id, status)",
)

_COMMENTS = (
    "COMMENT ON TABLE team_run_revisions IS "
    "'运行修订记录(T2): requirement/plan/context 修订留痕, 重规划不删历史'",
    "COMMENT ON TABLE team_run_attempts IS "
    "'执行尝试记录(T2): 每次真实执行一行, 先落库后启动成员; "
    "usage_reported=false 表示消耗未知'",
    "COMMENT ON TABLE team_run_events IS "
    "'持久运行事件(T2): 全部 run 有序留痕(seq 单调), SSE 仅为传输通道'",
    "COMMENT ON TABLE team_run_budget_reservations IS "
    "'预算预留/结算(T2): 调用前原子预留, 结算后按实际用量落账, 防超售'",
)


def upgrade() -> None:
    # 建表（幂等）
    for ddl in _TABLES:
        op.execute(ddl)
    # 索引（幂等）
    for ddl in _INDEXES:
        op.execute(ddl)
    # 注释
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    for table in (
        "team_run_budget_reservations",
        "team_run_events",
        "team_run_attempts",
        "team_run_revisions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
