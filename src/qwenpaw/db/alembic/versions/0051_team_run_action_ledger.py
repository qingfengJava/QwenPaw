# -*- coding: utf-8 -*-
"""Team run action ledger: business actions with idempotency keys.

Revision ID: 0051_team_run_action_ledger
Revises: 0050_team_run_contracts_ledger
Create Date: 2026-09-21

专家团职责协作 T4（可信委派/工具治理/动作账本）：

- ``team_run_actions``：业务外部动作账本——动作**先落库后执行**
  （registered → executed/failed/reverted），``action_key`` 在 run
  内对**活跃登记**唯一（部分唯一索引，reverted 释放幂等键——恢复/
  撤权后同一逻辑动作可重新登记，历史以独立行留痕）；
- ``envelope``：服务端生成的 TrustedExecutionEnvelope 快照（控制面
  授权边界留痕；传输只经内部可信通道，外部请求自填无效）。

全部 DDL 幂等。（psql twin: changelog 20260921/03）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0051_team_run_action_ledger"
down_revision = "0050_team_run_contracts_ledger"
branch_labels = None
depends_on = None

_TABLE = """
    CREATE TABLE IF NOT EXISTS team_run_actions (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        run_id VARCHAR(64) NOT NULL,
        node_key VARCHAR(128) NOT NULL DEFAULT '',
        attempt_id VARCHAR(64) NOT NULL DEFAULT '',
        action_type VARCHAR(64) NOT NULL DEFAULT '',
        action_key VARCHAR(128) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'registered',
        envelope JSONB NOT NULL DEFAULT '{}'::jsonb,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_team_run_actions PRIMARY KEY (tenant_id, id)
    )
"""

# 兼容修复：早期草稿用全列唯一约束（reverted 也会占用幂等键），升级
# 幂等移除后改用部分唯一索引（reverted 不占键，可重新登记）
_DROP_LEGACY_CONSTRAINT = (
    "ALTER TABLE team_run_actions "
    "DROP CONSTRAINT IF EXISTS uq_team_run_actions_key"
)

# 幂等键唯一（活跃登记）：registered/executed/failed 占键防重复执行
# 外部副作用；reverted（恢复/撤权）释放键，同一逻辑动作可重新登记
_UQ_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_team_run_actions_key
    ON team_run_actions (tenant_id, run_id, action_key)
    WHERE status <> 'reverted'
"""

_INDEX = """
    CREATE INDEX IF NOT EXISTS ix_team_run_actions_run
    ON team_run_actions (tenant_id, run_id, status)
"""

_COMMENTS = (
    "COMMENT ON TABLE team_run_actions IS "
    "'业务动作账本(T4): 外部动作先落库后执行, action_key run 内幂等, "
    "envelope 为服务端可信载荷快照'",
    "COMMENT ON COLUMN team_run_actions.status IS "
    "'状态: registered-已登记未执行, executed-已执行, "
    "failed-执行失败, reverted-已回滚/作废'",
)


def upgrade() -> None:
    # 建表（幂等）
    op.execute(_TABLE)
    # 早期草稿的全列唯一约束移除（幂等；reverted 不再占用幂等键）
    op.execute(_DROP_LEGACY_CONSTRAINT)
    # 活跃登记的部分唯一索引（幂等）
    op.execute(_UQ_INDEX)
    # 查询辅助索引（幂等）
    op.execute(_INDEX)
    # 注释
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_run_actions")
