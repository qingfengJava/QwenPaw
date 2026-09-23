# -*- coding: utf-8 -*-
"""Agent skill binding plane (``agent_skill_bindings`` PG storage).

Revision ID: 0024_agent_skill_bindings
Revises: 0023_skill_catalog
Create Date: 2026-09-11

数字员工技能绑定表 ``agent_skill_bindings``：每个数字员工显式装配的
技能引用（enabled/channels/员工级 config/origin），对应
``workspaces/{agent_id}/skill.json`` manifest（workspace-skill-manifest.v1）
的逐条目投影。列结构与 ``agent_model_slots`` 范式对齐并增加
``origin`` 来源维度。引用化装配语义：装配 = 写一行绑定，技能体文件
零拷贝（池内唯一副本），运行时按"私有自建 → 池 → 内置"顺序解析。
``QWENPAW_STORAGE_BACKEND`` 为 ``json``（默认）时不参与任何读写路径，
``dual`` 影子双写，``pg`` 权威读（manifest 兜底）。
（psql twin: changelog 20260911/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0024_agent_skill_bindings"
down_revision = "0023_skill_catalog"
branch_labels = None
depends_on = None

_CREATE_AGENT_SKILL_BINDINGS = """
CREATE TABLE IF NOT EXISTS agent_skill_bindings (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    skill_name VARCHAR(128) NOT NULL,
    origin VARCHAR(16) NOT NULL DEFAULT 'pool',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    channels JSONB NOT NULL DEFAULT '["all"]',
    config JSONB NOT NULL DEFAULT '{}',
    tags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_skill_bindings
        PRIMARY KEY (tenant_id, agent_id, skill_name)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE agent_skill_bindings IS "
    "'数字员工技能绑定表（员工显式装配的技能引用；workspace skill.json "
    "manifest 的 PG 落库平面，装配动作只写绑定行、技能体零拷贝，"
    "运行时解析优先级：私有自建 → 池 → 内置）'",
    "COMMENT ON COLUMN agent_skill_bindings.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN agent_skill_bindings.agent_id IS "
    "'数字员工 ID（智能体档案 ID，如 python-fullstack）'",
    "COMMENT ON COLUMN agent_skill_bindings.skill_name IS "
    "'技能名（池内技能目录名或员工私有技能名）'",
    "COMMENT ON COLUMN agent_skill_bindings.origin IS "
    "'装配来源: pool-从技能池引用, builtin-内置技能, private-员工私有自建'",
    "COMMENT ON COLUMN agent_skill_bindings.enabled IS "
    "'是否启用（禁用后该技能不注入员工运行时）'",
    "COMMENT ON COLUMN agent_skill_bindings.channels IS "
    "'生效渠道数组 JSONB（[\"all\"] 或 [\"console\",\"dingtalk\"...]）'",
    "COMMENT ON COLUMN agent_skill_bindings.config IS "
    "'员工级环境变量覆盖 JSONB（覆盖池级 config 同名字段）'",
    "COMMENT ON COLUMN agent_skill_bindings.tags IS "
    "'员工级标签 JSONB（可空，随池同步）'",
    "COMMENT ON COLUMN agent_skill_bindings.created_at IS "
    "'创建时间（首次装配时写入）'",
    "COMMENT ON COLUMN agent_skill_bindings.updated_at IS "
    "'更新时间（每次装配变更时刷新）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260911/01 的等价 alembic 路径）
    op.execute(_CREATE_AGENT_SKILL_BINDINGS)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_skill_bindings")
