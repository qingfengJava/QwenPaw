-- ============================================================
-- 变更说明: 内置专家体系信息架构 —— experts / expert_teams 两表
--           各新增 sample_tasks（"专家帮你做"任务模板）与
--           showcase（使用案例）两个 JSONB 列：
--           1) sample_tasks：[{title, prompt}]，市场/详情页
--              "专家帮你做"区块的数据源；点击模板即以 prompt
--              为 kickoff（单专家）或 goal（专家团 run）发起任务；
--              管理端可编辑（运营位，非代码硬编码）
--           2) showcase：[{title, desc, tags[]}]，静态使用案例
--              卡数据源（管理端可编辑 + 出厂内置）；专家团详情
--              另有 team_runs 真实交付投影（"最近交付"）与静态
--              案例分区并存，运营打底 + 真实佐证
-- 变更时间: 2026-08-18
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0011_builtin_sample_tasks（Revises 0010_workforce_team_runs）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（ADD COLUMN IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. experts：任务模板 + 使用案例
-- ------------------------------------------------------------

ALTER TABLE experts ADD COLUMN IF NOT EXISTS sample_tasks JSONB NOT NULL DEFAULT '[]';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS showcase JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN experts.sample_tasks IS '"专家帮你做"任务模板数组 [{title, prompt}]：详情页点击模板即以 prompt 为 kickoff 召唤该专家；管理端可编辑';
COMMENT ON COLUMN experts.showcase IS '使用案例数组 [{title, desc, tags[]}]：静态运营位（管理端可编辑 + 出厂内置），与聊天直答无 run 依赖';

-- ------------------------------------------------------------
-- 2. expert_teams：任务模板 + 使用案例
-- ------------------------------------------------------------

ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS sample_tasks JSONB NOT NULL DEFAULT '[]';
ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS showcase JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN expert_teams.sample_tasks IS '"任务示例"模板数组 [{title, prompt}]：详情页点击模板即以 prompt 为 goal 创建专家团 run；管理端可编辑';
COMMENT ON COLUMN expert_teams.showcase IS '使用案例数组 [{title, desc, tags[]}]：静态运营位；与 team_runs 真实交付投影（"最近交付"）分区并存';

-- ------------------------------------------------------------
-- 3. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0011_builtin_sample_tasks';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0011_builtin_sample_tasks');
    END IF;
END $$;

COMMIT;
