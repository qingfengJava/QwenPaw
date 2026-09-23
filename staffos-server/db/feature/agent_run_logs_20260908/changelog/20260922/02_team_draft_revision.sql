-- [变更说明] 为 expert_teams 添加 draft_revision 列（CAS 乐观锁）
-- [变更时间] 2026-09-22
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- draft_revision: 草稿修订号，每次 PATCH 成功递增，发布不重置。
-- 客户端携带 expected_revision 做 CAS 校验，冲突返回 409。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'expert_teams'
          AND column_name = 'draft_revision'
    ) THEN
        ALTER TABLE expert_teams
            ADD COLUMN draft_revision integer NOT NULL DEFAULT 0;
    END IF;
END $$;
