# -*- coding: utf-8 -*-
"""Personal skill bundles plane (``agent_skill_bundles`` PG storage).

Revision ID: 0036_agent_skill_bundles
Revises: 0035_cron_jobs_owner
Create Date: 2026-09-17

个人技能包权威表 ``agent_skill_bundles``（双平面模型的 S2 用户个人平面）：
承载**用户个人技能**的完整文件树，与员工共享技能刻意分表——

- 共享技能维持既有「技能池 + workspace skill.json 文件链」平面
  （``skill_catalog`` / ``agent_skill_bindings`` / ``skill_content_snapshots``），
  本表**不**承载共享技能，避免三平面（池/绑定/个人）语义分叉；
- 个人技能是 user×agent 维度的私有资产：``owner_user_id`` 非空即个人技能，
  仅 owner 本人 + 平台管理员可见可改（跨人严格隔离），``files`` 存整棵
  技能目录树（SKILL.md + references/ + scripts/ 的 path→content 扁平映射），
  运行时物化到 ``workspace/.personal_skills/{user}/{skill}/`` 参与并集扫描
  （不进共享 manifest）。

归属快照列（department_id / project_id）与其它 S2 个人资产表对齐，写入时
经 org 目录解析，供 ops 按部门检索/归属统计。``QWENPAW_STORAGE_BACKEND``
为 ``json``（默认）时本表不参与任何读写路径（个人技能零动作降级为不可用），
``dual``/``pg`` 时以本表为个人技能唯一权威源。
（psql twin: changelog 20260917/04，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0036_agent_skill_bundles"
down_revision = "0035_cron_jobs_owner"
branch_labels = None
depends_on = None

_CREATE_AGENT_SKILL_BUNDLES = """
CREATE TABLE IF NOT EXISTS agent_skill_bundles (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    files JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    department_id TEXT,
    project_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_skill_bundles
        PRIMARY KEY (tenant_id, agent_id, owner_user_id, name)
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_agent_skill_bundles_owner "
    "ON agent_skill_bundles (tenant_id, agent_id, owner_user_id)",
)

_COMMENTS = (
    "COMMENT ON TABLE agent_skill_bundles IS "
    "'个人技能包权威表（S2 用户个人平面：user×agent 私有技能的完整文件树；"
    "与共享技能池/绑定平面刻意分表，仅承载个人技能，避免三平面语义分叉。"
    "json 后端零动作、dual/pg 权威；运行时物化到 .personal_skills 参与并集扫描）'",
    "COMMENT ON COLUMN agent_skill_bundles.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN agent_skill_bundles.agent_id IS "
    "'数字员工 ID（workspace 目录名，与 agent_skill_bindings 同约定）'",
    "COMMENT ON COLUMN agent_skill_bundles.owner_user_id IS "
    "'个人技能归属用户（非空即个人技能；仅 owner+平台管理员可见可改，跨人隔离）'",
    "COMMENT ON COLUMN agent_skill_bundles.name IS "
    "'技能名（规范化目录名；同 owner+agent 内唯一，与共享技能名空间独立）'",
    "COMMENT ON COLUMN agent_skill_bundles.files IS "
    "'技能目录全树 JSONB（path→content 扁平映射，含 SKILL.md/references/scripts；"
    "物化到 .personal_skills/{user}/{skill}/ 的权威源）'",
    "COMMENT ON COLUMN agent_skill_bundles.enabled IS "
    "'是否启用（禁用后不物化、不注入该用户运行时）'",
    "COMMENT ON COLUMN agent_skill_bundles.version IS "
    "'内容版本号（同技能单调递增，乐观并发/变更追溯用）'",
    "COMMENT ON COLUMN agent_skill_bundles.department_id IS "
    "'owner 部门归属快照（写入时经 org 目录解析的部门 path；无 PG 或"
    "owner 无部门时为空；ops 按部门检索/归属统计用）'",
    "COMMENT ON COLUMN agent_skill_bundles.project_id IS "
    "'owner 项目归属快照（预留列；个人技能暂无项目维度，恒空）'",
    "COMMENT ON COLUMN agent_skill_bundles.created_at IS "
    "'创建时间（首次写入时生成）'",
    "COMMENT ON COLUMN agent_skill_bundles.updated_at IS "
    "'更新时间（每次内容变更时刷新）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260917/04 的等价 alembic 路径）
    op.execute(_CREATE_AGENT_SKILL_BUNDLES)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_skill_bundles_owner")
    op.execute("DROP TABLE IF EXISTS agent_skill_bundles")
