# -*- coding: utf-8 -*-
"""Team config versions: immutable publish snapshots (expert teams T1).

Revision ID: 0049_team_config_versions
Revises: 0048_binding_principal
Create Date: 2026-09-21

专家团职责协作 T1（团队配置与发布版本）：

- 新表 ``expert_team_versions``：每次团队发布写入一行不可变快照
  （version=发布时团队版本号，team 内唯一），``spec`` 保存成员职责
  与 orchestration 完整配置供审计与运行版本核对；
- 行不可更新（重发布=新行），删除团队时按 tenant+team 级联清理由
  应用层负责（本迁移不建外键，与既有库约定一致）；
- 快照只用于审计比对，执行时仍检查即时撤权，不成为新授权来源。

全部 DDL 幂等。（psql twin: changelog 20260921/01）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0049_team_config_versions"
down_revision = "0048_binding_principal"
branch_labels = None
depends_on = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS expert_team_versions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    team_id VARCHAR(64) NOT NULL,
    version INTEGER NOT NULL,
    spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_team_versions PRIMARY KEY (tenant_id, team_id, version),
    CONSTRAINT ck_expert_team_versions_version CHECK (version > 0)
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_expert_team_versions_team "
    "ON expert_team_versions (tenant_id, team_id)"
)

_COMMENTS = (
    "COMMENT ON TABLE expert_team_versions IS "
    "'团队发布配置不可变快照(T1): 每次发布一行, 重发布=新行; "
    "spec 保存成员职责与 orchestration 完整快照, 仅审计用途'",
    "COMMENT ON COLUMN expert_team_versions.version IS "
    "'发布时的团队版本号(expert_teams.version 快照, team 内唯一)'",
    "COMMENT ON COLUMN expert_team_versions.spec IS "
    "'发布快照: name/description/mode/members(含 member_role)/orchestration'",
    "COMMENT ON COLUMN expert_team_versions.published_by IS '发布操作人'",
)


def upgrade() -> None:
    op.execute(_CREATE_TABLE)
    op.execute(_INDEX)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS expert_team_versions")
