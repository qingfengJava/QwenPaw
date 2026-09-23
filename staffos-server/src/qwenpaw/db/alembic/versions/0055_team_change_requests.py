# -*- coding: utf-8 -*-
"""AI team change requests (persistent proposal ledger, P5).

Revision ID: 0055_team_change_requests
Revises: 0054_p2_two_level_publish
Create Date: 2026-09-22

P5 AI 修改安全闭环：

- AI 对话修改团队配置时，模型只能提出候选变更请求，不能直接写
  草稿；用户在聊天界面确认后才由 HTTP 确认端点执行 CAS 写操作。
- ``team_change_requests`` 持久化提案生命周期：
  pending → applying → applied/rejected/expired/conflict/failed。

幂等 DDL。（psql twin: changelog 20260922/04_team_change_requests.sql）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0055_team_change_requests"
down_revision = "0054_p2_two_level_publish"
branch_labels = None
depends_on = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS team_change_requests (
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
    request_id      VARCHAR(64)  NOT NULL,
    team_id         VARCHAR(64)  NOT NULL,
    operator_id     VARCHAR(128) NOT NULL,
    session_id      VARCHAR(128) NOT NULL DEFAULT '',
    kind            VARCHAR(32)  NOT NULL DEFAULT 'save_draft',
    base_revision   INTEGER      NOT NULL DEFAULT 0,
    base_published_version INTEGER NOT NULL DEFAULT 0,
    candidate_hash  VARCHAR(64)  NOT NULL DEFAULT '',
    candidate_payload JSONB      NOT NULL DEFAULT '{}'::jsonb,
    validation_result JSONB      NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    error_message   TEXT         NOT NULL DEFAULT '',
    expires_at      TIMESTAMP WITH TIME ZONE
                    NOT NULL DEFAULT (now() + interval '30 minutes'),
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    applied_at      TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_team_change_requests PRIMARY KEY (tenant_id, request_id)
)
"""

_IDX_TEAM = (
    "CREATE INDEX IF NOT EXISTS idx_team_change_requests_team "
    "ON team_change_requests (tenant_id, team_id, created_at DESC)"
)

_IDX_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_team_change_requests_status "
    "ON team_change_requests (tenant_id, status) "
    "WHERE status IN ('pending', 'applying')"
)

_TABLE_COMMENT = (
    "COMMENT ON TABLE team_change_requests IS "
    "'AI 修改团队配置的持久化提案（用户确认后执行）'"
)

_COMMENTS = (
    ("tenant_id", "租户标识"),
    ("request_id", "提案唯一 ID（UUID）"),
    ("team_id", "目标团队 ID"),
    ("operator_id", "发起操作的用户名（认证上下文）"),
    ("session_id", "来源会话 ID（AI 对话 session）"),
    ("kind", "提案类型：save_draft / publish"),
    ("base_revision", "创建时的草稿修订号（CAS 基准）"),
    ("base_published_version", "创建时的已发布版本号"),
    ("candidate_hash", "候选内容 SHA-256 摘要（防篡改比对）"),
    ("candidate_payload", "候选变更内容（JSON 结构化补丁）"),
    ("validation_result", "校验结果（issues 列表 + 差异卡）"),
    (
        "status",
        "状态：pending/applying/applied/rejected/expired/conflict/failed",
    ),
    ("error_message", "失败/冲突时的错误信息"),
    ("expires_at", "候选过期时间（默认 30 分钟）"),
    ("created_at", "创建时间"),
    ("updated_at", "状态更新时间"),
    ("applied_at", "实际执行时间"),
)


def upgrade() -> None:
    # 建表（幂等）
    op.execute(_CREATE_TABLE)
    # 索引（幂等）
    op.execute(_IDX_TEAM)
    op.execute(_IDX_STATUS)
    # 注释（幂等：COMMENT 天然幂等）
    op.execute(_TABLE_COMMENT)
    for column, comment in _COMMENTS:
        op.execute(
            f"COMMENT ON COLUMN team_change_requests.{column} IS '{comment}'"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_change_requests")
