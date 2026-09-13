-- [变更说明] 定时任务台账统一 + 执行记录对齐会话日志：三表扩展
--            1) expert_scheduled_tasks 增 source/origin 列——台账升级为数字员工
--               全部定时任务的统一台账，对话创建链路经注册观察者自动投影入账；
--            2) expert_task_runs 增 run_id/session_id 列——执行记录轻量列表行，
--               详情层经 run_id 复用 agent_runs/agent_run_spans 会话日志权威结构；
--            3) agent_runs 增 cron_job_id 列——定时任务执行反查键，配合
--               RunLogStartHook 的 source 修正（cron 来源不再误标为 chat）。
-- [变更时间] 2026-09-13
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0029_cron_task_ledger_unify

-- 台账来源列（存量行默认 ui，与历史 UI 创建语义一致）
ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS
source VARCHAR(16) NOT NULL DEFAULT 'ui';

ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS
origin JSONB NOT NULL DEFAULT '{}';

-- 执行记录运行关联列（存量历史行空串，详情回退摘要展示）
ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS
run_id VARCHAR(64) NOT NULL DEFAULT '';

ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS
session_id TEXT NOT NULL DEFAULT '';

-- 运行日志定时任务反查键（会话执行为 NULL）
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS
cron_job_id VARCHAR(64);

-- source 枚举约束（PG 无 ADD CONSTRAINT IF NOT EXISTS，按名称幂等判定）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_expert_scheduled_tasks_source'
    ) THEN
        ALTER TABLE expert_scheduled_tasks ADD CONSTRAINT
        ck_expert_scheduled_tasks_source
        CHECK (source IN ('ui', 'chat', 'api'));
    END IF;
END
$$;

-- 台账按来源筛选索引
CREATE INDEX IF NOT EXISTS idx_expert_scheduled_tasks_source
ON expert_scheduled_tasks (tenant_id, expert_id, source);

-- 执行记录 → 运行详情跳转键（空串历史行不进索引）
CREATE INDEX IF NOT EXISTS idx_expert_task_runs_run
ON expert_task_runs (tenant_id, run_id) WHERE run_id <> '';

-- 运行日志按定时任务反查索引
CREATE INDEX IF NOT EXISTS ix_agent_runs_cron_job
ON agent_runs (tenant_id, cron_job_id, started_at)
WHERE cron_job_id IS NOT NULL;

COMMENT ON COLUMN expert_scheduled_tasks.source IS
'任务来源: ui-界面创建, chat-对话创建, api-开放接口创建（注册观察者自动投影，统一台账单一出口）';
COMMENT ON COLUMN expert_scheduled_tasks.origin IS
'来源端原始载荷投影 JSONB（对话创建时保留 CronJobSpec 关键字段如 dispatch/channel，便于溯源）';
COMMENT ON COLUMN expert_task_runs.run_id IS
'关联 agent_runs 的运行 ID（详情层复用会话日志权威结构：span 树 + 会话回放；历史行为空串）';
COMMENT ON COLUMN expert_task_runs.session_id IS
'本次执行落库的会话 ID（share_session=false 时为 cron:{job_id} 独立会话）';
COMMENT ON COLUMN agent_runs.cron_job_id IS
'定时任务 ID（source=cron 的执行反查键；会话执行为 NULL）';
