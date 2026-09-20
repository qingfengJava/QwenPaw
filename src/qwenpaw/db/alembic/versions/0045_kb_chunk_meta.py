# -*- coding: utf-8 -*-
"""KB chunk meta: ontology link columns on kb_chunks (ontology T2).

Revision ID: 0045_kb_chunk_meta
Revises: 0044_kb_org_scope
Create Date: 2026-09-20

知识本体平台 T2（Evidence 层证据元数据预留，迁移先行、写入后接）：

- ``knowledge_id``：切片归属的本体知识节点 id（T4 摄入管线回填；
  NULL = 未挂接本体，检索编排器按 NULL 容忍处理）；
- ``entity_ids``：切片提及的实体 id 数组（JSONB；T4 抽取回填，供
  T5 编排器做实体级过滤与一跳邻接扩展）；
- ``valid_from`` / ``valid_to``：事实有效期（TIMESTAMPTZ；NULL =
  无时效约束），供时效性过滤与「过期证据降权」使用。

全部列 NULL-able、纯加列（零回填、零默认值），存量行为语义不变；
索引待 T5 编排器定稿查询形态后再建（避免为未落地的查询建索引）。

全部 DDL 幂等（ADD COLUMN IF NOT EXISTS）。psql twin: changelog
20260920/03（分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0045_kb_chunk_meta"
down_revision = "0044_kb_org_scope"
branch_labels = None
depends_on = None

_ADD_COLUMNS = (
    "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS knowledge_id VARCHAR(64)",
    "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS entity_ids JSONB",
    "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ",
    "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ",
)

_COMMENTS = (
    "COMMENT ON COLUMN kb_chunks.knowledge_id IS "
    "'切片归属的本体知识节点 id（T4 摄入回填；NULL=未挂接本体）'",
    "COMMENT ON COLUMN kb_chunks.entity_ids IS "
    "'切片提及的实体 id 数组（JSONB；T4 抽取回填，编排器过滤/扩展用）'",
    "COMMENT ON COLUMN kb_chunks.valid_from IS "
    "'事实有效期起（NULL=无时效约束；时效过滤与过期降权用）'",
    "COMMENT ON COLUMN kb_chunks.valid_to IS "
    "'事实有效期止（NULL=无时效约束；时效过滤与过期降权用）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE kb_chunks DROP COLUMN IF EXISTS valid_to",
    )
    op.execute(
        "ALTER TABLE kb_chunks DROP COLUMN IF EXISTS valid_from",
    )
    op.execute(
        "ALTER TABLE kb_chunks DROP COLUMN IF EXISTS entity_ids",
    )
    op.execute(
        "ALTER TABLE kb_chunks DROP COLUMN IF EXISTS knowledge_id",
    )
