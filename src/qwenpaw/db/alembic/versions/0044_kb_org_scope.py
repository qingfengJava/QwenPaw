# -*- coding: utf-8 -*-
"""KB org scope: kb_spaces.org_id + scope CHECK 'org' (ontology T1).

Revision ID: 0044_kb_org_scope
Revises: 0043_employee_profile
Create Date: 2026-09-20

知识本体平台 T1（组织级知识库，四级权限 personal/team/org/enterprise）：

- ``kb_spaces.org_id``：org scope 的归属组织（org 即租户边界，单租户
  部署恒为 ``default``，与 ``orgs.id`` 同域）；存量行回填 ``default``
  语义等价（此前无组织维度，全员即组织）。
- ``ck_kb_spaces_scope`` 约束换血：枚举扩 ``'org'``。用幂等 DO 块先删
  旧约束再建新约束（约束名不变，模型层 ``VALID_SCOPES`` 同步扩枚举）。
- ``ix_kb_spaces_org``：按租户+组织检索库清单的覆盖索引。

全部 DDL 幂等（ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS /
CREATE INDEX IF NOT EXISTS）。模型侧 ``KnowledgeBase``/``KbSpace`` 已带
``org_id`` 字段（默认 ``default``），json 平面无 DDL、语义同批生效。

（psql twin: changelog 20260920/02，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0044_kb_org_scope"
down_revision = "0043_employee_profile"
branch_labels = None
depends_on = None

_ADD_COLUMN = (
    "ALTER TABLE kb_spaces ADD COLUMN IF NOT EXISTS org_id "
    "VARCHAR(64) NOT NULL DEFAULT 'default'",
)

# 约束换血：先删旧 CHECK（0034 建的个人/团队/企业三值约束）再建四值新约束；
# DO 块保证重复执行不报错（约束不存在时 DROP 静默通过）。
_SWAP_SCOPE_CHECK = (
    """
    DO $$
    BEGIN
        ALTER TABLE kb_spaces
            DROP CONSTRAINT IF EXISTS ck_kb_spaces_scope;
        ALTER TABLE kb_spaces
            ADD CONSTRAINT ck_kb_spaces_scope
            CHECK (scope IN ('personal', 'team', 'org', 'enterprise'));
    END
    $$;
    """,
)

_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_kb_spaces_org "
    "ON kb_spaces (tenant_id, org_id)",
)

_COMMENTS = (
    "COMMENT ON COLUMN kb_spaces.org_id IS "
    "'org scope 的归属组织 id（org 即租户边界，与 orgs.id 同域；"
    "单租户部署恒为 default；org 库对组织内全部认证成员可读）'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMN:
        op.execute(statement)
    for statement in _SWAP_SCOPE_CHECK:
        op.execute(statement)
    for statement in _CREATE_INDEX:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_spaces_org")
    # 回滚约束前先确认无 org 库残留（有则手动迁移后重试）
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM kb_spaces WHERE scope = 'org') THEN "
        "RAISE NOTICE 'org-scope spaces remain; CHECK constraint kept'; "
        "ELSE "
        "ALTER TABLE kb_spaces DROP CONSTRAINT IF EXISTS ck_kb_spaces_scope; "
        "ALTER TABLE kb_spaces ADD CONSTRAINT ck_kb_spaces_scope "
        "CHECK (scope IN ('personal', 'team', 'enterprise')); "
        "END IF; "
        "END $$;",
    )
    op.execute(
        "ALTER TABLE kb_spaces DROP COLUMN IF EXISTS org_id",
    )
