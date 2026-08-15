-- ============================================================
-- 变更说明: 表时间戳规范补齐 —— 按项目 SQL 规范为每张业务表补全
--           created_at / updated_at：
--           expert_team_members、published_experts 补双时间戳列，
--           feed_events、token_usage_events 补 updated_at 列
--           （append-only 表不执行 UPDATE，updated_at 恒为插入时刻）
-- 变更时间: 2026-08-15
-- 变更人:   清风
-- 适用环境: test / prod（PostgreSQL 14+）
-- 对应迁移: alembic 0004_table_timestamps（Revises 0003_xian_extras）
-- 快照同步: 本文件内容已同步至 ../../test.sql 与 ../../prod.sql
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行；
--           ADD COLUMN ... NOT NULL DEFAULT now() 为瞬时操作（PG 11+）
-- 依赖说明: 需先执行 01_enterprise_schema.sql（四张表已存在）
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. expert_team_members：补 created_at / updated_at
-- ------------------------------------------------------------

ALTER TABLE expert_team_members
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();
ALTER TABLE expert_team_members
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();

COMMENT ON COLUMN expert_team_members.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN expert_team_members.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 2. published_experts：补 created_at / updated_at
--    （published_at 保留业务语义：发布动作时间）
-- ------------------------------------------------------------

ALTER TABLE published_experts
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();
ALTER TABLE published_experts
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();

COMMENT ON COLUMN published_experts.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN published_experts.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 3. feed_events：补 updated_at（append-only，恒为插入时刻）
-- ------------------------------------------------------------

ALTER TABLE feed_events
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();

COMMENT ON COLUMN feed_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';

-- ------------------------------------------------------------
-- 4. token_usage_events：补 updated_at（append-only，恒为插入时刻）
-- ------------------------------------------------------------

ALTER TABLE token_usage_events
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now();

COMMENT ON COLUMN token_usage_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';

-- ------------------------------------------------------------
-- 5. Alembic 版本标记（与 alembic upgrade head 等效）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0004_table_timestamps';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0004_table_timestamps');
    END IF;
END $$;

COMMIT;
