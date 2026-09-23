# -*- coding: utf-8 -*-
"""Skill content snapshot plane (``skill_content_snapshots`` PG storage).

Revision ID: 0025_skill_content_snapshots
Revises: 0024_agent_skill_bindings
Create Date: 2026-09-11

技能体内容快照表 ``skill_content_snapshots``：技能目录
（SKILL.md + references/ + scripts/）的 zip 压缩冷备（BYTEA）。
设计理念：技能是数据资产，PG 是唯一权威源 —— 文件目录只承担运行时
热路径（AgentScope 要求真实目录），任何文件丢失（换服务器/误删/
磁盘清理）都可通过启动对账从本表自动解压物化重建，实现
"恢复数据库 = 完整恢复"。``owner_agent_id`` 为空串表示池技能快照，
为员工 ID 表示该员工私有技能快照。内置技能不写快照（随安装包分发，
重装即恢复）。``QWENPAW_STORAGE_BACKEND`` 为 ``json``（默认）时
零动作，``dual`` 影子写，``pg`` 权威平面。
（psql twin: changelog 20260911/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0025_skill_content_snapshots"
down_revision = "0024_agent_skill_bindings"
branch_labels = None
depends_on = None

_CREATE_SKILL_CONTENT_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS skill_content_snapshots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    owner_agent_id VARCHAR(64) NOT NULL DEFAULT '',
    skill_name VARCHAR(128) NOT NULL,
    content_zip BYTEA NOT NULL,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_skill_content_snapshots
        PRIMARY KEY (tenant_id, owner_agent_id, skill_name)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE skill_content_snapshots IS "
    "'技能体内容快照表（技能目录 zip 冷备；文件丢失时启动对账自动"
    "解压物化自愈，实现恢复数据库=完整恢复）'",
    "COMMENT ON COLUMN skill_content_snapshots.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN skill_content_snapshots.owner_agent_id IS "
    "'归属员工 ID（空串=技能池快照；员工 ID=该员工私有技能快照）'",
    "COMMENT ON COLUMN skill_content_snapshots.skill_name IS "
    "'技能名（同 skill_pool 目录名或 workspace 私有技能名）'",
    "COMMENT ON COLUMN skill_content_snapshots.content_zip IS "
    "'技能体 zip 字节（SKILL.md+references/+scripts/，继承 200MB 上限，"
    "排除 OS 缓存伪影）'",
    "COMMENT ON COLUMN skill_content_snapshots.content_hash IS "
    "'快照对应 SKILL.md sha256（与 skill_catalog.content_hash 对齐校验"
    "快照新旧，漂移时以文件为准重打）'",
    "COMMENT ON COLUMN skill_content_snapshots.created_at IS "
    "'创建时间（首次打快照时写入）'",
    "COMMENT ON COLUMN skill_content_snapshots.updated_at IS "
    "'更新时间（技能体每次变更重打快照时刷新）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260911/01 的等价 alembic 路径）
    op.execute(_CREATE_SKILL_CONTENT_SNAPSHOTS)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_content_snapshots")
