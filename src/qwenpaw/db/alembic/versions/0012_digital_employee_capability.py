# -*- coding: utf-8 -*-
"""Digital employee capability layer (StaffDeck-inspired).

Revision ID: 0012_digital_employee_capability
Revises: 0011_builtin_sample_tasks
Create Date: 2026-08-30

Brings the StaffDeck-style digital-employee capability plane onto the
experts domain (design doc:
``docs/design/2026-08-30-digital-employee-capability-layer.md``):

- ``experts`` +4 profile columns (department / work_styles /
  work_modes / hire_date); online status stays derived, never stored.
- ``expert_resource_bindings``: capability mount hub for
  sop / knowledge_base / tool (skills keep living in ``expert_skills``
  — that table stays the publish-chain authority).
- ``sops`` + ``sop_versions``: SOP as a versioned process *asset*
  injected into workforce planning/verification — never a hard
  state machine.
- ``expert_memories``: bucketed long-term memory
  (profile / preference / fact, dedup-key idempotent).
- ``expert_scheduled_tasks`` + ``expert_task_runs``: scheduled-task
  projection ledger + execution records (scheduling authority stays
  in CronManager; job ids prefixed ``expert_task_``).
- ``message_feedback``: per-message 👍/👎 collection.
- ``evolution_proposals``: feedback-driven change proposals with a
  human review lifecycle.

Idempotent DDL only — no destructive statements.

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0012_digital_employee_capability"
down_revision = "0011_builtin_sample_tasks"
branch_labels = None
depends_on = None

_EXPERT_PROFILE_DDLS = (
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS department TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_styles JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_modes JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE experts ADD COLUMN IF NOT EXISTS hire_date TIMESTAMPTZ",
)

_BINDINGS_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS expert_resource_bindings (
        tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
        expert_id     VARCHAR(64) NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id   TEXT NOT NULL,
        enabled       BOOLEAN NOT NULL DEFAULT TRUE,
        seq           INTEGER NOT NULL DEFAULT 0,
        metadata      JSONB NOT NULL DEFAULT '{}',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_expert_resource_bindings
            PRIMARY KEY (tenant_id, expert_id, resource_type, resource_id),
        CONSTRAINT ck_expert_resource_bindings_type
            CHECK (resource_type IN ('sop', 'knowledge_base', 'tool'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_expert_resource_bindings_expert "
    "ON expert_resource_bindings (tenant_id, expert_id, resource_type)",
)

_SOPS_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS sops (
        tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
        id              VARCHAR(64) NOT NULL,
        name            TEXT NOT NULL,
        description     TEXT NOT NULL DEFAULT '',
        business_domain TEXT NOT NULL DEFAULT '',
        goal            TEXT NOT NULL DEFAULT '',
        nodes           JSONB NOT NULL DEFAULT '[]',
        edges           JSONB NOT NULL DEFAULT '[]',
        slots           JSONB NOT NULL DEFAULT '[]',
        status          TEXT NOT NULL DEFAULT 'draft',
        version         INTEGER NOT NULL DEFAULT 1,
        owner_id        TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_sops PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_sops_status CHECK (status IN ('draft', 'published', 'archived'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sop_versions (
        tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
        sop_id       VARCHAR(64) NOT NULL,
        version      INTEGER NOT NULL,
        snapshot     JSONB NOT NULL,
        change_note  TEXT NOT NULL DEFAULT '',
        published_by TEXT,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_sop_versions PRIMARY KEY (tenant_id, sop_id, version)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sops_owner ON sops (tenant_id, owner_id)",
)

_MEMORIES_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS expert_memories (
        tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
        id         VARCHAR(64) NOT NULL,
        expert_id  VARCHAR(64) NOT NULL,
        user_id    TEXT NOT NULL DEFAULT '',
        kind       TEXT NOT NULL,
        content    TEXT NOT NULL,
        importance REAL NOT NULL DEFAULT 0.5,
        dedup_key  TEXT NOT NULL DEFAULT '',
        metadata   JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_expert_memories PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_expert_memories_kind
            CHECK (kind IN ('profile', 'preference', 'fact'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_memories_dedup "
    "ON expert_memories (tenant_id, expert_id, user_id, kind, dedup_key) "
    "WHERE dedup_key <> ''",
    "CREATE INDEX IF NOT EXISTS idx_expert_memories_scope "
    "ON expert_memories (tenant_id, expert_id, user_id, kind)",
)

_SCHEDULING_DDLS = (
    """
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
        CONSTRAINT pk_expert_scheduled_tasks PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_expert_scheduled_tasks_type
            CHECK (schedule_type IN ('cron', 'once')),
        CONSTRAINT ck_expert_scheduled_tasks_status
            CHECK (status IN ('active', 'paused', 'completed', 'archived'))
    )
    """,
    """
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
        CONSTRAINT pk_expert_task_runs PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_expert_task_runs_status
            CHECK (status IN ('running', 'succeeded', 'failed'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_task_runs_idem "
    "ON expert_task_runs (tenant_id, task_id, scheduled_for) "
    "WHERE scheduled_for IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_expert_task_runs_task "
    "ON expert_task_runs (tenant_id, task_id, started_at DESC)",
)

_FEEDBACK_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS message_feedback (
        tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
        id          VARCHAR(64) NOT NULL,
        message_id  TEXT NOT NULL,
        session_id  TEXT NOT NULL DEFAULT '',
        expert_id   TEXT NOT NULL DEFAULT '',
        user_id     TEXT NOT NULL DEFAULT '',
        rating      TEXT NOT NULL,
        comment     TEXT NOT NULL DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_message_feedback PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_message_feedback_rating CHECK (rating IN ('up', 'down'))
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_once "
    "ON message_feedback (tenant_id, message_id, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_message_feedback_expert "
    "ON message_feedback (tenant_id, expert_id, created_at DESC)",
)

_EVOLUTION_DDLS = (
    """
    CREATE TABLE IF NOT EXISTS evolution_proposals (
        tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
        id           VARCHAR(64) NOT NULL,
        expert_id    VARCHAR(64) NOT NULL,
        title        TEXT NOT NULL,
        trigger_type TEXT NOT NULL DEFAULT 'feedback',
        risk_level   TEXT NOT NULL DEFAULT 'low',
        hypothesis   TEXT NOT NULL DEFAULT '',
        evidence     JSONB NOT NULL DEFAULT '[]',
        candidate    JSONB NOT NULL DEFAULT '{}',
        status       TEXT NOT NULL DEFAULT 'draft',
        reviewed_by  TEXT,
        reviewed_at  TIMESTAMPTZ,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_evolution_proposals PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_evolution_proposals_trigger
            CHECK (trigger_type IN ('feedback', 'manual', 'audit')),
        CONSTRAINT ck_evolution_proposals_risk
            CHECK (risk_level IN ('low', 'medium', 'high')),
        CONSTRAINT ck_evolution_proposals_status
            CHECK (status IN ('draft', 'ready_for_review', 'approved',
                              'rejected', 'published', 'rolled_back'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_evolution_proposals_expert "
    "ON evolution_proposals (tenant_id, expert_id, status, updated_at DESC)",
)

_ALL_GROUPS = (
    _EXPERT_PROFILE_DDLS,
    _BINDINGS_DDLS,
    _SOPS_DDLS,
    _MEMORIES_DDLS,
    _SCHEDULING_DDLS,
    _FEEDBACK_DDLS,
    _EVOLUTION_DDLS,
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260830/01 的等价 alembic 路径）
    for group in _ALL_GROUPS:
        for ddl in group:
            op.execute(ddl)


def downgrade() -> None:
    # 降级仅移除能力层新表（experts 档案列保留：存量业务数据不受影响）
    for table in (
        "evolution_proposals",
        "message_feedback",
        "expert_task_runs",
        "expert_scheduled_tasks",
        "expert_memories",
        "sop_versions",
        "sops",
        "expert_resource_bindings",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
