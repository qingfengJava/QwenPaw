# -*- coding: utf-8 -*-
"""P2 two-level publish columns (usage_mode / published_version / spec_hash).

Revision ID: 0054_p2_two_level_publish
Revises: 0053_team_draft_revision
Create Date: 2026-09-22

P2 两级发布（配置草稿 → 发布版本）：

- ``experts``：usage_mode（team_only/shared 使用范围）+
  published_version（最新发布版本指针）；
- ``expert_teams``：published_version（当前已发布团队版本指针）；
- ``expert_team_members``：expert_version（草稿选定的成员发布版本，
  NULL=未指定）；
- ``expert_team_versions``：source_draft_revision / spec_hash /
  publish_request_id（发布审计与幂等）；
- ``published_experts``：spec_hash（发布包内容哈希）。

幂等 DDL。（psql twin: changelog 20260922/03_p2_two_level_publish.sql）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0054_p2_two_level_publish"
down_revision = "0053_team_draft_revision"
branch_labels = None
depends_on = None


def _add_column(table: str, column: str, ddl: str) -> None:
    """幂等加列（information_schema 判断后 ALTER，与 psql twin 同口径）。"""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{table}'
                  AND column_name = '{column}'
            ) THEN
                ALTER TABLE {table} ADD COLUMN {ddl};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # 1. experts: 使用范围 + 最新发布版本指针
    _add_column(
        "experts", "usage_mode",
        "usage_mode TEXT NOT NULL DEFAULT 'shared'",
    )
    _add_column(
        "experts", "published_version",
        "published_version INTEGER NOT NULL DEFAULT 0",
    )
    op.execute(
        "COMMENT ON COLUMN experts.usage_mode IS "
        "'使用范围(P2): team_only=团队专属, shared=可独立使用; "
        "存量迁移为 shared'"
    )
    op.execute(
        "COMMENT ON COLUMN experts.published_version IS "
        "'员工最新发布版本指针(P2): 指向 published_experts.version, "
        "0=从未发布'"
    )
    # 2. expert_teams: 当前已发布团队版本指针
    _add_column(
        "expert_teams", "published_version",
        "published_version INTEGER NOT NULL DEFAULT 0",
    )
    op.execute(
        "COMMENT ON COLUMN expert_teams.published_version IS "
        "'当前已发布团队版本指针(P2): 指向 expert_team_versions.version, "
        "0=从未发布'"
    )
    # 3. expert_team_members: 草稿选定的成员发布版本
    _add_column(
        "expert_team_members", "expert_version",
        "expert_version INTEGER",
    )
    op.execute(
        "COMMENT ON COLUMN expert_team_members.expert_version IS "
        "'草稿显式选定的成员发布版本(P2): 发布时禁止为空, NULL=未指定'"
    )
    # 4. expert_team_versions: 发布审计三列
    _add_column(
        "expert_team_versions", "source_draft_revision",
        "source_draft_revision INTEGER NOT NULL DEFAULT 0",
    )
    _add_column(
        "expert_team_versions", "spec_hash",
        "spec_hash VARCHAR(64) NOT NULL DEFAULT ''",
    )
    _add_column(
        "expert_team_versions", "publish_request_id",
        "publish_request_id VARCHAR(128) NOT NULL DEFAULT ''",
    )
    op.execute(
        "COMMENT ON COLUMN expert_team_versions.source_draft_revision IS "
        "'来源草稿修订号(P2): 发布时基于哪个 draft_revision, "
        "用于冲突检测和审计'"
    )
    op.execute(
        "COMMENT ON COLUMN expert_team_versions.spec_hash IS "
        "'发布包内容哈希(P2): spec 摘要 SHA-256, 幂等发布和完整性校验'"
    )
    op.execute(
        "COMMENT ON COLUMN expert_team_versions.publish_request_id IS "
        "'发布请求幂等键(P2): 绑定确认请求 ID, 重复请求返回原结果'"
    )
    # 5. published_experts: 发布包内容哈希
    _add_column(
        "published_experts", "spec_hash",
        "spec_hash VARCHAR(64) NOT NULL DEFAULT ''",
    )
    op.execute(
        "COMMENT ON COLUMN published_experts.spec_hash IS "
        "'发布包内容哈希(P2): spec 摘要 SHA-256, 发布记录与激活指针保持一致'"
    )


def downgrade() -> None:
    # 加列迁移的回滚：逆序删除（幂等）
    for statement in (
        "ALTER TABLE published_experts "
        "DROP COLUMN IF EXISTS spec_hash",
        "ALTER TABLE expert_team_versions "
        "DROP COLUMN IF EXISTS publish_request_id",
        "ALTER TABLE expert_team_versions "
        "DROP COLUMN IF EXISTS spec_hash",
        "ALTER TABLE expert_team_versions "
        "DROP COLUMN IF EXISTS source_draft_revision",
        "ALTER TABLE expert_team_members "
        "DROP COLUMN IF EXISTS expert_version",
        "ALTER TABLE expert_teams "
        "DROP COLUMN IF EXISTS published_version",
        "ALTER TABLE experts "
        "DROP COLUMN IF EXISTS published_version",
        "ALTER TABLE experts DROP COLUMN IF EXISTS usage_mode",
    ):
        op.execute(statement)
