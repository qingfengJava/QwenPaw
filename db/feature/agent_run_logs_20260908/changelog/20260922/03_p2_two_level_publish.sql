-- [变更说明] P2 两级发布：experts/expert_teams/expert_team_members/expert_team_versions/published_experts 补列
-- [变更时间] 2026-09-22
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- 1. experts: usage_mode（使用范围）+ published_version（最新发布版本指针）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'experts'
          AND column_name = 'usage_mode'
    ) THEN
        ALTER TABLE experts
            ADD COLUMN usage_mode text NOT NULL DEFAULT 'shared';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'experts'
          AND column_name = 'published_version'
    ) THEN
        ALTER TABLE experts
            ADD COLUMN published_version integer NOT NULL DEFAULT 0;
    END IF;
END $$;

COMMENT ON COLUMN experts.usage_mode IS
    '使用范围(P2): team_only=团队专属, shared=可独立使用; 存量迁移为 shared';
COMMENT ON COLUMN experts.published_version IS
    '员工最新发布版本指针(P2): 指向 published_experts.version, 0=从未发布';

-- 2. expert_teams: published_version（当前已发布团队版本指针）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'expert_teams'
          AND column_name = 'published_version'
    ) THEN
        ALTER TABLE expert_teams
            ADD COLUMN published_version integer NOT NULL DEFAULT 0;
    END IF;
END $$;

COMMENT ON COLUMN expert_teams.published_version IS
    '当前已发布团队版本指针(P2): 指向 expert_team_versions.version, 0=从未发布';

-- 3. expert_team_members: expert_version（草稿选定的成员发布版本）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'expert_team_members'
          AND column_name = 'expert_version'
    ) THEN
        ALTER TABLE expert_team_members
            ADD COLUMN expert_version integer;
    END IF;
END $$;

COMMENT ON COLUMN expert_team_members.expert_version IS
    '草稿显式选定的成员发布版本(P2): 发布时禁止为空, NULL=未指定';

-- 4. expert_team_versions: source_draft_revision + spec_hash + publish_request_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'expert_team_versions'
          AND column_name = 'source_draft_revision'
    ) THEN
        ALTER TABLE expert_team_versions
            ADD COLUMN source_draft_revision integer NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'expert_team_versions'
          AND column_name = 'spec_hash'
    ) THEN
        ALTER TABLE expert_team_versions
            ADD COLUMN spec_hash varchar(64) NOT NULL DEFAULT '';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'expert_team_versions'
          AND column_name = 'publish_request_id'
    ) THEN
        ALTER TABLE expert_team_versions
            ADD COLUMN publish_request_id varchar(128) NOT NULL DEFAULT '';
    END IF;
END $$;

COMMENT ON COLUMN expert_team_versions.source_draft_revision IS
    '来源草稿修订号(P2): 发布时基于哪个 draft_revision, 用于冲突检测和审计';
COMMENT ON COLUMN expert_team_versions.spec_hash IS
    '发布包内容哈希(P2): spec 摘要 SHA-256, 幂等发布和完整性校验';
COMMENT ON COLUMN expert_team_versions.publish_request_id IS
    '发布请求幂等键(P2): 绑定确认请求 ID, 重复请求返回原结果';

-- 5. published_experts: spec_hash（发布包内容哈希）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'published_experts'
          AND column_name = 'spec_hash'
    ) THEN
        ALTER TABLE published_experts
            ADD COLUMN spec_hash varchar(64) NOT NULL DEFAULT '';
    END IF;
END $$;

COMMENT ON COLUMN published_experts.spec_hash IS
    '发布包内容哈希(P2): spec 摘要 SHA-256, 发布记录与激活指针保持一致';
