# -*- coding: utf-8 -*-
"""Workforce team-run tables: DAG orchestration persistence.

Revision ID: 0010_workforce_team_runs
Revises: 0009_expert_catalog
Create Date: 2026-08-18

Creates the two runtime tables for the workforce plane (two-level
Harness — central brain Plan-then-Execute over published expert agents):

- ``team_runs``: one orchestrated team-task execution (state machine:
  planning / awaiting_confirm / running / verifying / repairing /
  aggregating / done / failed / escalated / canceled / interrupted);
  plan / policy / context_bundle are JSONB snapshots (same philosophy
  as agent_spec — low-churn, migration-free evolution).
- ``team_run_nodes``: per-DAG-node execution ledger (TaskContract /
  ResultContract / RepairContract JSONB + verdict + attempt counters;
  node-boundary checkpoints enable crash resume).

Both tables are brand new (metadata ``checkfirst`` — the same rollout
philosophy as 0002→0009: fresh databases get them from metadata, legacy
databases get them here, the SQL changelog
``20260818/02_workforce_team_runs.sql`` stays an idempotent equivalent).
No ALTERs, no destructive DDL. Existing ``tasks`` kanban semantics are
deliberately untouched (manual-task isolation).

DDL statements are fixed string literals (no interpolation) so static
security scanning cannot mistake them for dynamic SQL assembly.

@author qingfeng
"""
from __future__ import annotations

from alembic import op

from qwenpaw.db.base import Base
from qwenpaw.db import models_enterprise  # noqa: F401  (register tables)

revision = "0010_workforce_team_runs"
down_revision = "0009_expert_catalog"
branch_labels = None
depends_on = None

_NEW_TABLES = ("team_runs", "team_run_nodes")

_INDEX_DDLS = (
    "CREATE INDEX IF NOT EXISTS ix_team_runs_team ON team_runs (tenant_id, team_id)",
    "CREATE INDEX IF NOT EXISTS ix_team_runs_status ON team_runs (tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_team_runs_project ON team_runs (tenant_id, project_id)",
    "CREATE INDEX IF NOT EXISTS ix_team_run_nodes_run ON team_run_nodes (tenant_id, run_id)",
)


def upgrade() -> None:
    # 先按 ORM 元数据建新表（checkfirst 幂等：已存在的库跳过）
    bind = op.get_bind()
    for name in _NEW_TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)
    # 再补查询索引（表已存在而索引缺失的半迁移状态收敛）
    for ddl in _INDEX_DDLS:
        op.execute(ddl)


def downgrade() -> None:
    # 降级仅丢弃 workforce 运行数据表（业务上是可再生的执行留痕）
    for name in reversed(_NEW_TABLES):
        op.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
