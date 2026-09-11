# -*- coding: utf-8 -*-
"""Skill pool catalog plane (``skill_catalog`` PG storage).

Revision ID: 0023_skill_catalog
Revises: 0022_agent_document_revisions
Create Date: 2026-09-11

技能池目录表 ``skill_catalog``：平台技能池的 PG 元数据权威平面
（技能名/来源/版本/标签/池级 config/automation/中文映射等），
对应 ``skill_pool/skill.json`` manifest（skill-pool-manifest.v1）的
逐条目投影。``QWENPAW_STORAGE_BACKEND`` 为 ``json``（默认）时不参与
任何读写路径，``dual`` 影子双写（manifest primary），``pg`` 权威读
（manifest 兜底）；技能体文件仍以 ``skill_pool/<name>/`` 目录为
运行时载体，数据库内容快照见 ``0025_skill_content_snapshots``。
（psql twin: changelog 20260911/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0023_skill_catalog"
down_revision = "0022_agent_document_revisions"
branch_labels = None
depends_on = None

_CREATE_SKILL_CATALOG = """
CREATE TABLE IF NOT EXISTS skill_catalog (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    skill_name VARCHAR(128) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'customized',
    installed_from VARCHAR(128) NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    version_text VARCHAR(64) NOT NULL DEFAULT '',
    emoji VARCHAR(16) NOT NULL DEFAULT '',
    builtin_language VARCHAR(8) NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]',
    config JSONB NOT NULL DEFAULT '{}',
    automation JSONB NOT NULL DEFAULT '{}',
    external BOOLEAN NOT NULL DEFAULT FALSE,
    external_path TEXT NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    display_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    description_zh TEXT NOT NULL DEFAULT '',
    protected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_skill_catalog PRIMARY KEY (tenant_id, skill_name)
)
"""

_COMMENTS = (
    "COMMENT ON TABLE skill_catalog IS "
    "'技能池目录表（平台技能池的 PG 元数据权威平面：名称/来源/版本/标签/"
    "池级配置/自动化策略/中文映射；skill_pool/skill.json manifest 的逐条目"
    "投影，json 后端零动作、dual 影子写、pg 权威读）'",
    "COMMENT ON COLUMN skill_catalog.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN skill_catalog.skill_name IS "
    "'技能名（skill_pool 下的目录名，同 manifest 键）'",
    "COMMENT ON COLUMN skill_catalog.source IS "
    "'技能来源: builtin-内置, customized-自定义/市场安装'",
    "COMMENT ON COLUMN skill_catalog.installed_from IS "
    "'安装来源标识（hub 来源: skills-sh/github/lobehub/qwenpaw/"
    "modelscope/aliyun/skillsmp/clawhub/url/zip；空串=本地创建）'",
    "COMMENT ON COLUMN skill_catalog.source_url IS "
    "'市场原始地址（hub 安装时记录，便于溯源与更新检查）'",
    "COMMENT ON COLUMN skill_catalog.version_text IS "
    "'技能版本（SKILL.md frontmatter version）'",
    "COMMENT ON COLUMN skill_catalog.emoji IS "
    "'技能图标 emoji（metadata.qwenpaw.emoji）'",
    "COMMENT ON COLUMN skill_catalog.builtin_language IS "
    "'内置技能语言变体: en/zh（非内置为空串）'",
    "COMMENT ON COLUMN skill_catalog.tags IS "
    "'标签数组 JSONB（如 [\"文档\",\"办公\"]）'",
    "COMMENT ON COLUMN skill_catalog.config IS "
    "'池级环境变量配置 JSONB（装配到员工时随行下发）'",
    "COMMENT ON COLUMN skill_catalog.automation IS "
    "'自动化策略 JSONB（auto_update/auto_sync/targets/synced_hash；"
    "引用化后 auto_sync 语义退役仅作兼容保留）'",
    "COMMENT ON COLUMN skill_catalog.external IS "
    "'是否外部目录技能（skill_paths 额外根，只读）'",
    "COMMENT ON COLUMN skill_catalog.external_path IS "
    "'外部技能目录绝对路径（external=true 时有效）'",
    "COMMENT ON COLUMN skill_catalog.content_hash IS "
    "'技能体内容指纹（SKILL.md sha256；空串=待对账/内容丢失）'",
    "COMMENT ON COLUMN skill_catalog.display_name_zh IS "
    "'中文显示名映射（技能卡片优先展示；空串回退英文 name）'",
    "COMMENT ON COLUMN skill_catalog.description_zh IS "
    "'中文描述映射（面向中文用户的一句话解释；空串回退英文描述）'",
    "COMMENT ON COLUMN skill_catalog.protected IS "
    "'是否受保护（禁止删除）'",
    "COMMENT ON COLUMN skill_catalog.created_at IS "
    "'创建时间（首次入池时写入）'",
    "COMMENT ON COLUMN skill_catalog.updated_at IS "
    "'更新时间（每次技能变更时刷新）'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260911/01 的等价 alembic 路径）
    op.execute(_CREATE_SKILL_CATALOG)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_catalog")
