-- ============================================================
-- 变更说明: XianWork 项目扩展 —— 新增 project_bindings（项目资源绑定）、
--           project_automations（项目自动化）两张表，
--           projects 表新增 instructions 列（项目 SOP / 系统提示词）
-- 变更时间: 2026-08-14
-- 变更人:   清风
-- 适用环境: test / prod（PostgreSQL 14+）
-- 对应迁移: alembic 0003_xian_extras（Revises 0002_enterprise）
-- 快照同步: 本文件内容已同步至 ../../test.sql 与 ../../prod.sql
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- 依赖说明: 需先执行 01_enterprise_schema.sql（projects 表存在）
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 项目资源绑定（连接器 / 技能）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS project_bindings (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    id         VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    kind       TEXT NOT NULL,
    ref_id     TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT true,
    config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_project_bindings PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE project_bindings IS '项目资源绑定表（记录项目 AI 可用的连接器/技能；注册表权威在 console 面）';
COMMENT ON COLUMN project_bindings.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN project_bindings.id IS '绑定 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN project_bindings.project_id IS '所属项目 ID';
COMMENT ON COLUMN project_bindings.kind IS '资源类型：connector（MCP 客户端）/ skill（技能）';
COMMENT ON COLUMN project_bindings.ref_id IS '资源在其注册表内的标识（MCP client key / skill name）';
COMMENT ON COLUMN project_bindings.enabled IS '是否启用（false 时项目 AI 不可使用该资源）';
COMMENT ON COLUMN project_bindings.config IS '绑定级配置（JSONB，按 kind 定义结构）';
COMMENT ON COLUMN project_bindings.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN project_bindings.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE UNIQUE INDEX IF NOT EXISTS ux_project_bindings
    ON project_bindings (tenant_id, project_id, kind, ref_id);

-- ------------------------------------------------------------
-- 2. 项目自动化（定时任务）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS project_automations (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    project_id  VARCHAR(64) NOT NULL,
    name        TEXT NOT NULL,
    schedule    TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    cron_job_id VARCHAR(64),
    last_run_at TIMESTAMP WITH TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_project_automations PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE project_automations IS '项目自动化表（调度权威在项目智能体 cron 管理器，本表为项目面投影）';
COMMENT ON COLUMN project_automations.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN project_automations.id IS '自动化任务 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN project_automations.project_id IS '所属项目 ID';
COMMENT ON COLUMN project_automations.name IS '自动化任务名称（配置面板展示）';
COMMENT ON COLUMN project_automations.schedule IS '调度表达式（cron 语法）';
COMMENT ON COLUMN project_automations.prompt IS '触发时执行的任务提示词（由应用层写入）';
COMMENT ON COLUMN project_automations.enabled IS '是否启用';
COMMENT ON COLUMN project_automations.cron_job_id IS '项目智能体 cron 管理器中的任务 ID，可为 NULL（未注册）';
COMMENT ON COLUMN project_automations.last_run_at IS '最近一次执行时间，可为 NULL（从未执行）';
COMMENT ON COLUMN project_automations.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN project_automations.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_project_automations_project
    ON project_automations (tenant_id, project_id);

-- ------------------------------------------------------------
-- 3. projects 表增量：instructions 列
--    （0003 之前的库需要；全新库由快照建表时已含）
-- ------------------------------------------------------------

ALTER TABLE projects ADD COLUMN IF NOT EXISTS instructions TEXT;

COMMENT ON COLUMN projects.instructions IS '项目 SOP / 系统提示词（右侧配置面板展示，注入项目共享 AI）';

UPDATE projects SET instructions = '' WHERE instructions IS NULL;

-- ------------------------------------------------------------
-- 4. Alembic 版本标记（与 alembic upgrade 至 0003 等效）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0003_xian_extras';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0003_xian_extras');
    END IF;
END $$;

COMMIT;
