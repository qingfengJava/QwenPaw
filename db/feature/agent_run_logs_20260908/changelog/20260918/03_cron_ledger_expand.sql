-- [变更说明] cron 双台账收口 Phase 1（T13a EXPAND，设计文档 docs/design/
--            2026-09-18-cron-ledger-convergence.md）：expert 两表
--            （expert_scheduled_tasks/expert_task_runs）收口进 cron 双表前，
--            先补齐权威面缺失的执行留痕与统计字段——
--            1) cron_job_history 补 4 列：result_summary（执行结果摘要，
--               worklog 时间线标题来源）、run_id/session_id（关联 agent_runs
--               运行详情与会话回放的跳转键；模型早有且 manager 已赋值，
--               pg_repo INSERT 此前丢列，本次补齐落库面）、scheduled_for
--               （调度槽位时间：trigger=scheduled 时取 run_at，手动为空）；
--            2) cron_jobs 补 run_count：历史累计执行次数冗余计数
--               （append_history 同事务 +1；history 仅留最近 50 条，
--               COUNT 反推会被修剪窗截断——决策 D3）。
--            全部新列带默认值，写路径补列对老代码零影响；读路径切换
--            在 Phase 2（回填+委托），DROP expert 两表在 Phase 3。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0040_cron_ledger_expand
--
-- 全部 DDL 幂等（ADD COLUMN IF NOT EXISTS）。

ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS result_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS run_id VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS session_id TEXT NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS run_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN cron_job_history.result_summary IS '执行结果摘要（final_text 截断 500 字，worklog 时间线标题来源）';
COMMENT ON COLUMN cron_job_history.run_id IS '关联 agent_runs 的运行 ID（执行详情跳转键；text 任务为空）';
COMMENT ON COLUMN cron_job_history.session_id IS '本次执行落库的会话 ID（share_session=False 时为 cron:{job_id}，会话回放跳转键）';
COMMENT ON COLUMN cron_job_history.scheduled_for IS '调度槽位时间（trigger=scheduled 时等于 run_at，手动触发为空）';
COMMENT ON COLUMN cron_jobs.run_count IS '历史累计执行次数（append_history 同事务 +1；history 仅留最近 50 条，精确计数不能靠 COUNT 反推）';
