# -*- coding: utf-8 -*-
"""agent_documents 个人草稿维（owner_user_id + 表达式唯一索引）。

Revision ID: 0038_agent_documents_owner_draft
Revises: 0037_sops_owner_attributes
Create Date: 2026-09-18

T11 个人档案草稿（S2 用户个人平面）：

- ``owner_user_id``：NULL=员工共享行（admin/manager 写、发布链权威行）；
  非空=该用户的个人草稿行（employee 写四文档落本人 draft 行，不触共享行；
  与正式 agent_id 的 ``environment='draft'`` 组合承载个人草稿）；
- 唯一约束重建：旧约束 ``uq_agent_documents_doc``
  (tenant_id, agent_id, doc_type, environment) 删除，改为表达式唯一索引
  （``COALESCE(owner_user_id, '')``）——同一文档下多用户各持一份个人草稿
  互不冲突，共享行（owner 为 NULL）仍全局唯一；
- 存量行 ``owner_user_id`` 为 NULL，语义与旧行为完全一致。

全部 DDL 幂等（ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS /
CREATE UNIQUE INDEX IF NOT EXISTS）；个人草稿写路径不写
``agent_document_revisions``（快照链仅属于共享发布闸门，apply=promote
时在共享链落 revision）。

（psql twin: changelog 20260918/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0038_agent_documents_owner_draft"
down_revision = "0037_sops_owner_attributes"
branch_labels = None
depends_on = None

# 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
_ADD_COLUMNS = (
    "ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS owner_user_id "
    "VARCHAR(64)",
)

# 唯一约束重建：先删旧四元约束，再建 coalesce 表达式唯一索引（幂等）
_REBUILD_UNIQUE = (
    "ALTER TABLE agent_documents DROP CONSTRAINT IF EXISTS "
    "uq_agent_documents_doc",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_documents_doc_owner "
    "ON agent_documents (tenant_id, agent_id, doc_type, environment, "
    "COALESCE(owner_user_id, ''))",
)

_COMMENTS = (
    "COMMENT ON COLUMN agent_documents.owner_user_id IS "
    "'个人草稿 owner（NULL=员工共享行；非空=该用户的个人草稿行，与 "
    "environment=draft 组合；管理员应用 apply 后 promote 到共享行）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMNS:
        op.execute(statement)
    for statement in _REBUILD_UNIQUE:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_agent_documents_doc_owner")
    op.execute(
        "ALTER TABLE agent_documents ADD CONSTRAINT uq_agent_documents_doc "
        "UNIQUE (tenant_id, agent_id, doc_type, environment)",
    )
    op.execute(
        "ALTER TABLE agent_documents DROP COLUMN IF EXISTS owner_user_id",
    )
