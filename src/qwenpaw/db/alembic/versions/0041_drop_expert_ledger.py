# -*- coding: utf-8 -*-
"""Cron ledger convergence Phase 3: DROP the retired expert ledger tables.

Revision ID: 0041_drop_expert_ledger
Revises: 0040_cron_ledger_expand
Create Date: 2026-09-18

T13 cron 双台账收口 Phase 3（CONTRACT，设计文档 docs/design/
2026-09-18-cron-ledger-convergence.md §4.4）：expert 两表的全部读
字段已由 0040 补入 cron 双表、写路径已改基 CronManager 权威 +
CronLedgerReader 读回（scheduling.py / expert_capability.py 停写），
两张 legacy 台账表退役：

- ``expert_task_runs``（执行留痕 → cron_job_history）；
- ``expert_scheduled_tasks``（规格投影 → cron_jobs + spec.meta）。

前置（运维步骤，本迁移不含）：DROP 前 ``pg_dump`` 备份两表；先停写
观察业务无异常再 DROP（expand-contract 分变更日原则）。

``downgrade`` 内置完整重建 DDL（提取自 0012 建表 + 0029 加列/索引/
约束），幂等（CREATE TABLE / INDEX IF NOT EXISTS），作为回滚安全垫——
但重建后为空表，历史数据须从 DROP 前的 pg_dump 备份恢复。
（psql twin: changelog 20260918/04，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0041_drop_expert_ledger"
down_revision = "0040_cron_ledger_expand"
branch_labels = None
depends_on = None

# DROP 顺序：先 runs（子表语义）后 tasks；DROP TABLE 自动级联其索引
_DROP_STATEMENTS = (
    "DROP TABLE IF EXISTS expert_task_runs",
    "DROP TABLE IF EXISTS expert_scheduled_tasks",
)

# --- downgrade 重建 DDL（0012 建表 + 0029 加列，全部内联；幂等）---

_REBUILD_EXPERT_SCHEDULED_TASKS = """
CREATE TABLE IF NOT EXISTS expert_scheduled_tasks (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            VARCHAR(64) NOT NULL,
    expert_id     VARCHAR(64) NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    task_prompt   TEXT NOT NULL,
    schedule_type TEXT NOT NULL DEFAULT 'cron',
    schedule_json JSONB NOT NULL DEFAULT '{}',
    timezone      TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status        TEXT NOT NULL DEFAULT 'active',
    cron_job_id   TEXT NOT NULL DEFAULT '',
    next_run_at   TIMESTAMPTZ,
    last_run_at   TIMESTAMPTZ,
    last_status   TEXT NOT NULL DEFAULT '',
    run_count     BIGINT NOT NULL DEFAULT 0,
    owner_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        VARCHAR(16) NOT NULL DEFAULT 'ui',
    origin        JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT pk_expert_scheduled_tasks PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_expert_scheduled_tasks_type
        CHECK (schedule_type IN ('cron', 'once')),
    CONSTRAINT ck_expert_scheduled_tasks_status
        CHECK (status IN ('active', 'paused', 'completed', 'archived')),
    CONSTRAINT ck_expert_scheduled_tasks_source
        CHECK (source IN ('ui', 'chat', 'api'))
)
"""

_REBUILD_EXPERT_TASK_RUNS = """
CREATE TABLE IF NOT EXISTS expert_task_runs (
    tenant_id      VARCHAR(64) NOT NULL DEFAULT 'default',
    id             VARCHAR(64) NOT NULL,
    task_id        VARCHAR(64) NOT NULL,
    expert_id      VARCHAR(64) NOT NULL,
    scheduled_for  TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'running',
    result_summary TEXT NOT NULL DEFAULT '',
    error          TEXT NOT NULL DEFAULT '',
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    run_id         VARCHAR(64) NOT NULL DEFAULT '',
    session_id     TEXT NOT NULL DEFAULT '',
    CONSTRAINT pk_expert_task_runs PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_expert_task_runs_status
        CHECK (status IN ('running', 'succeeded', 'failed'))
)
"""

_REBUILD_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_expert_scheduled_tasks_source "
    "ON expert_scheduled_tasks (tenant_id, expert_id, source)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_task_runs_idem "
    "ON expert_task_runs (tenant_id, task_id, scheduled_for) "
    "WHERE scheduled_for IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_expert_task_runs_task "
    "ON expert_task_runs (tenant_id, task_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_expert_task_runs_run "
    "ON expert_task_runs (tenant_id, run_id) WHERE run_id <> ''",
)


def upgrade() -> None:
    # 幂等 DROP（psql changelog 20260918/04 的等价 alembic 路径）
    for statement in _DROP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # 重建两表（内联 0012 建表 + 0029 加列/约束），再补索引；全幂等。
    # 注意：重建为空表，历史数据须从 DROP 前的 pg_dump 备份恢复。
    op.execute(_REBUILD_EXPERT_SCHEDULED_TASKS)
    op.execute(_REBUILD_EXPERT_TASK_RUNS)
    for statement in _REBUILD_INDEXES:
        op.execute(statement)
