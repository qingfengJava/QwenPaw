-- [变更说明] SOP 表增加归属快照两列（department_id / project_id），补齐
--            S2 个人资产的业务域归属（SOP 私有能力化后 owner_id = 归属员工 id）：
--            1) department_id 为 owner 部门归属快照（写入时经 org 目录解析的部门
--               path：员工 owner 取其治理行归属部门，用户名 owner 按部门成员解析；
--               无 PG 或 owner 无部门时为空）；行诞生即快照，随 promote/fork/
--               rollback 复制，不随重复发布抖动；
--            2) project_id 为预留列（SOP 暂无项目维度，恒空）；
--            3) 两列为普通可查询投影（非 JSONB 内字段），ops 按部门检索/归属统计
--               用；存量行 NULL 无越权语义变化（可见性仍由 environment + owner_id
--               决定：“个人 draft 仅 owner、production 全员”）。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0037_sops_owner_attributes
--
-- 全部 DDL 幂等（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE sops ADD COLUMN IF NOT EXISTS department_id TEXT;
ALTER TABLE sops ADD COLUMN IF NOT EXISTS project_id TEXT;

-- 归属检索索引（tenant + department）：ops 按部门检索/归属统计走此
CREATE INDEX IF NOT EXISTS ix_sops_department
    ON sops (tenant_id, department_id);

COMMENT ON COLUMN sops.department_id IS
    'owner 部门归属快照（写入时经 org 目录解析的部门 path；员工 owner '
    '取治理行归属部门，用户名 owner 按部门成员解析；无 PG 或 owner 无'
    '部门时为空；ops 按部门检索/归属统计用）';
COMMENT ON COLUMN sops.project_id IS
    'owner 项目归属快照（预留列；SOP 暂无项目维度，恒空）';