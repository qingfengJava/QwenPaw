-- ============================================================
-- 变更说明: 专家团职责协作 T1 —— 团队配置与发布版本：
--           新表 expert_team_versions（不可变发布快照）：每次团队发布
--           写入一行（version=发布时团队版本号, team 内唯一），spec
--           保存成员职责与 orchestration 完整快照供审计与运行版本核对；
--           重发布=新行，快照仅审计用途，不成为新授权来源。
-- 变更时间: 2026-09-21
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0049_team_config_versions（Revises 0048_binding_principal）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

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
);

CREATE INDEX IF NOT EXISTS ix_expert_team_versions_team
    ON expert_team_versions (tenant_id, team_id);

COMMENT ON TABLE expert_team_versions IS
    '团队发布配置不可变快照(T1): 每次发布一行, 重发布=新行; '
    'spec 保存成员职责与 orchestration 完整快照, 仅审计用途';

COMMENT ON COLUMN expert_team_versions.version IS
    '发布时的团队版本号(expert_teams.version 快照, team 内唯一)';

COMMENT ON COLUMN expert_team_versions.spec IS
    '发布快照: name/description/mode/members(含 member_role)/orchestration';

COMMENT ON COLUMN expert_team_versions.published_by IS '发布操作人';

-- 验证：SELECT count(*) FROM information_schema.tables
--       WHERE table_name='expert_team_versions';
