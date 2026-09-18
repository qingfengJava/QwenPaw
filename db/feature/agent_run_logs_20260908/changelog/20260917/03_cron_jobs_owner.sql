-- [变更说明] 定时任务表增加个人任务归属三列（owner_user_id /
--            department_id / project_id），落地双平面模型的 S2 用户个人平面：
--            1) owner_user_id 非空=个人任务（仅 owner 本人 + 平台管理员可见可改，
--               跨人严格隔离）；为空=员工共享任务（S1，使用授权内全员可见、
--               员工级管理授权者可写）；
--            2) department_id 为 owner 部门归属快照（写入时经 org 目录解析的部门
--               path，ops 按部门检索/归属统计用）；project_id 为预留列（个人定时
--               任务暂无项目维度，恒空）；
--            3) 三列均为 spec JSONB 内 CronJobSpec 同名字段的可查询投影——权威仍在
--               spec（随 json/pg 两平面往返），投影列仅供运维按 owner/部门检索。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0035_cron_jobs_owner
--
-- 存量行语义：owner_user_id 默认 NULL → 自动落"员工共享"语义，与既有全员可见
-- 行为一致，无越权收紧。全部 DDL 幂等（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS department_id TEXT;
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS project_id TEXT;

-- 归属检索索引（tenant + agent + owner）：list 过滤共享/个人与 ops 归属统计走此
CREATE INDEX IF NOT EXISTS ix_cron_jobs_owner
    ON cron_jobs (tenant_id, agent_id, owner_user_id);

COMMENT ON COLUMN cron_jobs.owner_user_id IS
    '个人任务归属用户（spec.owner_user_id 的可查询投影）: 非空=个人任务'
    '（仅 owner+平台管理员可见可改，跨人隔离）, 空=员工共享任务'
    '（使用授权内全员可见、员工级管理授权者可写）';
COMMENT ON COLUMN cron_jobs.department_id IS
    'owner 部门归属快照（写入时经 org 目录解析的部门 path；无 PG 或'
    'owner 无部门时为空；ops 按部门检索/归属统计用）';
COMMENT ON COLUMN cron_jobs.project_id IS
    'owner 项目归属快照（预留列；个人定时任务暂无项目维度，恒空）';
