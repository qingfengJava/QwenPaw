-- ============================================================
-- 变更说明: 专家团职责协作 T5 —— 累计活跃执行时间：team_runs 补列
--           active_seconds（秒）。各执行段在引擎收尾时累加，暂停/
--           中断/续跑不清零；时间熔断按"累计 + 本段耗时"判定
--           （协议8.5：恢复不清零，人工等待不计时）。
-- 变更时间: 2026-09-22
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0052_team_run_active_seconds（Revises 0051_team_run_action_ledger）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

ALTER TABLE team_runs
    ADD COLUMN IF NOT EXISTS active_seconds INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN team_runs.active_seconds IS
    '累计活跃执行时间秒(T5): 各执行段累加, 恢复/续跑不清零, '
    '时间熔断按累计值判定';

-- 验证：SELECT column_name FROM information_schema.columns
--       WHERE table_name = 'team_runs' AND column_name = 'active_seconds';
