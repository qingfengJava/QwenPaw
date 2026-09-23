# -*- coding: utf-8 -*-
"""SOP environment isolation (draft/production 双行 + promote).

Revision ID: 0030_sop_environment
Revises: 0029_cron_task_ledger_unify
Create Date: 2026-09-15

对齐 ``agent_documents`` 的 draft/production 双行隔离语义，为 SOP 资产补齐
环境维度：

- ``sops`` 增列 ``environment``（draft-调试草稿 / production-线上发布），
  默认 production，存量行天然落到线上环境；
- 主键由 ``(tenant_id, id)`` 重建为 ``(tenant_id, id, environment)``，
  允许同一 SOP 在草稿与线上各存一行，互不污染；
- ``sop_versions`` 版本链保持不变（仅跟 production 行，回滚/审计语义不变）。

（psql twin: changelog 20260915/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0030_sop_environment"
down_revision = "0029_cron_task_ledger_unify"
branch_labels = None
depends_on = None

# 幂等加列（存量库补列 / 新库 CREATE TABLE 后补齐，双路径安全）
_BACKFILL_DDLS = (
    "ALTER TABLE sops ADD COLUMN IF NOT EXISTS "
    "environment VARCHAR(16) NOT NULL DEFAULT 'production'",
)

# CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
_ADD_ENVIRONMENT_CHECK = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_sops_environment'
    ) THEN
        ALTER TABLE sops ADD CONSTRAINT
        ck_sops_environment
        CHECK (environment IN ('draft', 'production'));
    END IF;
END
$$;
"""

# 主键重建：先删旧 (tenant_id,id)，再建新 (tenant_id,id,environment)。
# DROP/ADD 均加 IF EXISTS/IF NOT EXISTS 守卫，重复执行不报错。
_REBUILD_PRIMARY_KEY_DROP = (
    "ALTER TABLE sops DROP CONSTRAINT IF EXISTS pk_sops",
)

_REBUILD_PRIMARY_KEY_ADD = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'pk_sops'
        ) THEN
            ALTER TABLE sops ADD CONSTRAINT pk_sops
            PRIMARY KEY (tenant_id, id, environment);
        END IF;
    END
    $$;
    """,
)

# 环境维度下的常用查询索引（按归属员工 + 环境过滤草稿/线上列表）
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sops_owner_env "
    "ON sops (tenant_id, owner_id, environment)",
)

_COMMENTS = (
    "COMMENT ON COLUMN sops.environment IS "
    "'环境: draft-调试草稿(工作台编辑), production-线上发布(运行时注入)；"
    "同一 SOP 两环境各存一行，promote 时草稿覆盖线上并写版本快照'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260915/01 的等价 alembic 路径）
    for ddl in _BACKFILL_DDLS:
        op.execute(ddl)
    op.execute(_ADD_ENVIRONMENT_CHECK)
    # 主键重建必须先删后加（列已存在，加 environment 到主键才不冲突）
    for ddl in _REBUILD_PRIMARY_KEY_DROP:
        op.execute(ddl)
    for ddl in _REBUILD_PRIMARY_KEY_ADD:
        op.execute(ddl)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 回退顺序：先索引，再主键退回 (tenant_id,id)，最后删列
    op.execute("DROP INDEX IF EXISTS idx_sops_owner_env")
    op.execute("ALTER TABLE sops DROP CONSTRAINT IF EXISTS pk_sops")
    op.execute(
        "ALTER TABLE sops ADD CONSTRAINT pk_sops PRIMARY KEY (tenant_id, id)",
    )
    op.execute(
        "ALTER TABLE sops DROP CONSTRAINT IF EXISTS ck_sops_environment",
    )
    op.execute("ALTER TABLE sops DROP COLUMN IF EXISTS environment")
