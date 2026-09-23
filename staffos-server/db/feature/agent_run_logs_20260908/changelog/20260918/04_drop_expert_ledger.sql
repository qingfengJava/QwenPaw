-- [变更说明] cron 双台账收口 Phase 3（T13d CONTRACT，设计文档 docs/design/
--            2026-09-18-cron-ledger-convergence.md §4.4）：expert 两表全部读
--            字段已由 0040 补入 cron 双表、写路径已改基 CronManager 权威 +
--            CronLedgerReader 读回（scheduling.py / expert_capability.py 停写），
--            两张 legacy 台账表退役 DROP——
--            1) expert_task_runs：执行留痕已落 cron_job_history；
--            2) expert_scheduled_tasks：规格投影已落 cron_jobs + spec.meta。
--            前置（运维步骤，本文件不含）：DROP 前 pg_dump 备份两表；先停写
--            观察业务无异常再 DROP（expand-contract 分变更日原则）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0041_drop_expert_ledger
--
-- DROP TABLE IF EXISTS 幂等；DROP 顺序先 runs 后 tasks（子表语义）。
-- 回滚：alembic downgrade 0041 内置完整重建 DDL（0012 建表 + 0029 加列/
--       索引/约束），但重建为空表，历史数据须从 DROP 前 pg_dump 备份恢复。

DROP TABLE IF EXISTS expert_task_runs;
DROP TABLE IF EXISTS expert_scheduled_tasks;
