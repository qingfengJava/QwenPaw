-- ============================================================
-- 变更说明: XianWork 企业域 schema —— 12 张企业表（orgs / departments /
--           department_members / projects / project_members / tasks /
--           feed_events / experts / expert_teams / expert_team_members /
--           published_experts / token_usage_events），
--           chats 表新增 project_id 列及 2 个支撑索引
-- 变更时间: 2026-08-14
-- 变更人:   清风
-- 适用环境: test / prod（PostgreSQL 14+）
-- 对应迁移: alembic 0002_enterprise（Revises 0001_initial）
-- 快照同步: 本文件内容已同步至 ../../test.sql 与 ../../prod.sql
--           （expert_team_members / published_experts / feed_events /
--            token_usage_events 的完整时间戳列由 03_table_timestamps.sql 补齐）
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- 依赖说明: 需先执行 0001_initial（chats 等基础表存在）
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 组织与部门
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orgs (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'standard',
    status      TEXT NOT NULL DEFAULT 'active',
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_orgs PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE orgs IS '企业组织表（租户边界，tenant_id == org.id）';
COMMENT ON COLUMN orgs.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN orgs.id IS '组织 ID（业务侧生成的 String(64)，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN orgs.name IS '组织名称';
COMMENT ON COLUMN orgs.slug IS '组织短标识（租户内唯一，用于 URL/展示）';
COMMENT ON COLUMN orgs.plan IS '套餐类型：standard 等';
COMMENT ON COLUMN orgs.status IS '组织状态：active 等';
COMMENT ON COLUMN orgs.settings IS '组织级设置项（JSONB，按需扩展）';
COMMENT ON COLUMN orgs.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN orgs.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE UNIQUE INDEX IF NOT EXISTS ux_orgs_slug ON orgs (tenant_id, slug);

CREATE TABLE IF NOT EXISTS departments (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    id           VARCHAR(64) NOT NULL,
    parent_id    VARCHAR(64),
    name         TEXT NOT NULL,
    path         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_departments PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE departments IS '部门表（树形结构，path 为部门 ID 物化路径）';
COMMENT ON COLUMN departments.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN departments.id IS '部门 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN departments.parent_id IS '父部门 ID，根部门为 NULL';
COMMENT ON COLUMN departments.name IS '部门名称';
COMMENT ON COLUMN departments.path IS '物化路径（a/b/c 形式的部门 ID 链，子树查询走前缀匹配）';
COMMENT ON COLUMN departments.description IS '部门描述';
COMMENT ON COLUMN departments.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN departments.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_departments_parent ON departments (tenant_id, parent_id);
CREATE INDEX IF NOT EXISTS ix_departments_path ON departments (tenant_id, path);

CREATE TABLE IF NOT EXISTS department_members (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    department_id VARCHAR(64) NOT NULL,
    username      TEXT NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_department_members PRIMARY KEY (tenant_id, department_id, username)
);

COMMENT ON TABLE department_members IS '部门成员表（部门关系的权威存储在 PG，users.json 仅保账号）';
COMMENT ON COLUMN department_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN department_members.department_id IS '部门 ID（联合主键成员）';
COMMENT ON COLUMN department_members.username IS '成员用户名（关联 users.json 账号，联合主键成员）';
COMMENT ON COLUMN department_members.created_at IS '入部门时间（DB 自动维护，UTC）';
COMMENT ON COLUMN department_members.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_department_members_user ON department_members (tenant_id, username);

-- ------------------------------------------------------------
-- 2. 项目与任务
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projects (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            VARCHAR(64) NOT NULL,
    department_id VARCHAR(64),
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'active',
    ai_binding    JSONB NOT NULL DEFAULT '{}'::jsonb,
    template_tag  TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_projects PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE projects IS '协作项目表（instructions 列由 02_xian_extras.sql 追加）';
COMMENT ON COLUMN projects.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN projects.id IS '项目 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN projects.department_id IS '所属部门 ID，可为 NULL（跨部门/无部门项目）';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.description IS '项目描述';
COMMENT ON COLUMN projects.status IS '项目状态：active 等';
COMMENT ON COLUMN projects.ai_binding IS '项目级 AI 绑定 {"kind": "expert"|"expert_team", "ref_id": ...}';
COMMENT ON COLUMN projects.template_tag IS '项目模板标签（空串表示非模板项目；由应用层写入）';
COMMENT ON COLUMN projects.created_by IS '创建人用户名';
COMMENT ON COLUMN projects.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN projects.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_projects_department ON projects (tenant_id, department_id);
CREATE INDEX IF NOT EXISTS ix_projects_status ON projects (tenant_id, status);

CREATE TABLE IF NOT EXISTS project_members (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    project_id VARCHAR(64) NOT NULL,
    username   TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_project_members PRIMARY KEY (tenant_id, project_id, username)
);

COMMENT ON TABLE project_members IS '项目成员表（成员资格与项目角色）';
COMMENT ON COLUMN project_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN project_members.project_id IS '项目 ID（联合主键成员）';
COMMENT ON COLUMN project_members.username IS '成员用户名（联合主键成员）';
COMMENT ON COLUMN project_members.role IS '项目角色：owner（所有者）/ editor（可编辑）/ viewer（只读）';
COMMENT ON COLUMN project_members.created_at IS '加入项目时间（DB 自动维护，UTC）';
COMMENT ON COLUMN project_members.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_project_members_user ON project_members (tenant_id, username);

CREATE TABLE IF NOT EXISTS tasks (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    project_id  VARCHAR(64) NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    assignee    TEXT,
    creator     TEXT NOT NULL,
    chat_id     VARCHAR(64),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_tasks PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE tasks IS '看板任务表（项目内四列看板）';
COMMENT ON COLUMN tasks.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN tasks.id IS '任务 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN tasks.project_id IS '所属项目 ID';
COMMENT ON COLUMN tasks.title IS '任务标题';
COMMENT ON COLUMN tasks.description IS '任务描述';
COMMENT ON COLUMN tasks.status IS '看板列状态：todo（待办）/ doing（进行中）/ paused（暂停）/ done（完成）';
COMMENT ON COLUMN tasks.assignee IS '经办人用户名，可为 NULL（未认领）';
COMMENT ON COLUMN tasks.creator IS '创建人用户名';
COMMENT ON COLUMN tasks.chat_id IS '弱引用 ChatSpec.id（任务由 AI 会话创建/执行时关联），可为 NULL';
COMMENT ON COLUMN tasks.sort_order IS '看板列内排序值（小值在前，由应用层维护）';
COMMENT ON COLUMN tasks.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN tasks.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_tasks_board ON tasks (tenant_id, project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS ix_tasks_assignee ON tasks (tenant_id, assignee, status);

CREATE TABLE IF NOT EXISTS feed_events (
    id         BIGSERIAL NOT NULL,
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    project_id VARCHAR(64) NOT NULL,
    actor      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

COMMENT ON TABLE feed_events IS '项目动态流（append-only 事件表，未来按月分区的候选；updated_at 由 03 补齐）';
COMMENT ON COLUMN feed_events.id IS '事件 ID（BIGSERIAL 自增主键）';
COMMENT ON COLUMN feed_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN feed_events.project_id IS '所属项目 ID';
COMMENT ON COLUMN feed_events.actor IS '触发者（用户名或 AI 标识）';
COMMENT ON COLUMN feed_events.kind IS '事件类型：task_created / task_status / comment / ai_reply / member_joined / member_left / project_updated';
COMMENT ON COLUMN feed_events.payload IS '事件负载（JSONB，按 kind 定义结构）';
COMMENT ON COLUMN feed_events.created_at IS '事件时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_feed_project ON feed_events (tenant_id, project_id, id DESC);

-- ------------------------------------------------------------
-- 3. 专家与专家团队
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS experts (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    name        TEXT NOT NULL,
    icon        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent_spec  JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'draft',
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_experts PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE experts IS '受管专家表（可发布的智能体定义）';
COMMENT ON COLUMN experts.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN experts.id IS '专家 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN experts.name IS '专家名称';
COMMENT ON COLUMN experts.icon IS '图标标识（由应用层写入）';
COMMENT ON COLUMN experts.description IS '专家描述';
COMMENT ON COLUMN experts.agent_spec IS '与 workspace agent.json 同构的 AgentProfileConfig 快照（JSONB）';
COMMENT ON COLUMN experts.status IS '状态：draft（草稿）/ published（已发布）/ archived（已归档）';
COMMENT ON COLUMN experts.version IS '当前版本号（发布时自增并落 published_experts 快照）';
COMMENT ON COLUMN experts.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN experts.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_experts_status ON experts (tenant_id, status);

CREATE TABLE IF NOT EXISTS expert_teams (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            VARCHAR(64) NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    mode          TEXT NOT NULL DEFAULT 'router',
    router_prompt TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_teams PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE expert_teams IS '专家团队表（轻量多智能体编排）';
COMMENT ON COLUMN expert_teams.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN expert_teams.id IS '团队 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN expert_teams.name IS '团队名称';
COMMENT ON COLUMN expert_teams.description IS '团队描述';
COMMENT ON COLUMN expert_teams.mode IS '编排模式：router（LLM 轮选成员）/ pipeline（顺序执行、输出链式传递）';
COMMENT ON COLUMN expert_teams.router_prompt IS 'router 模式的路由提示词';
COMMENT ON COLUMN expert_teams.status IS '状态：draft / published / archived';
COMMENT ON COLUMN expert_teams.version IS '当前版本号';
COMMENT ON COLUMN expert_teams.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN expert_teams.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_expert_teams_status ON expert_teams (tenant_id, status);

CREATE TABLE IF NOT EXISTS expert_team_members (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    team_id   VARCHAR(64) NOT NULL,
    expert_id VARCHAR(64) NOT NULL,
    role_hint TEXT NOT NULL DEFAULT '',
    seq       INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT pk_expert_team_members PRIMARY KEY (tenant_id, team_id, expert_id)
);

COMMENT ON TABLE expert_team_members IS '专家团队成员表（有序成员关系；created_at/updated_at 由 03 补齐）';
COMMENT ON COLUMN expert_team_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN expert_team_members.team_id IS '团队 ID（联合主键成员）';
COMMENT ON COLUMN expert_team_members.expert_id IS '专家 ID（联合主键成员）';
COMMENT ON COLUMN expert_team_members.role_hint IS '成员角色提示（供编排提示词引用）';
COMMENT ON COLUMN expert_team_members.seq IS '成员顺序（pipeline 模式执行序，小值在前）';

CREATE INDEX IF NOT EXISTS ix_expert_team_members_expert ON expert_team_members (tenant_id, expert_id);

CREATE TABLE IF NOT EXISTS published_experts (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    expert_id    VARCHAR(64) NOT NULL,
    version      INTEGER NOT NULL,
    spec         JSONB NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_published_experts PRIMARY KEY (tenant_id, expert_id, version)
);

COMMENT ON TABLE published_experts IS '专家版本发布快照表（不可变、只增不删；用户面始终读最新快照；created_at/updated_at 由 03 补齐）';
COMMENT ON COLUMN published_experts.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN published_experts.expert_id IS '专家 ID（联合主键成员）';
COMMENT ON COLUMN published_experts.version IS '发布的专家版本号（联合主键成员）';
COMMENT ON COLUMN published_experts.spec IS '发布时的完整专家 spec（JSONB）';
COMMENT ON COLUMN published_experts.published_by IS '发布操作人用户名';
COMMENT ON COLUMN published_experts.published_at IS '发布时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 4. Token 计量
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS token_usage_events (
    id                BIGSERIAL NOT NULL,
    tenant_id         VARCHAR(64) NOT NULL DEFAULT 'default',
    org_id            VARCHAR(64),
    user_id           TEXT,
    project_id        VARCHAR(64),
    agent_id          TEXT,
    provider_id       TEXT,
    model             TEXT,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

COMMENT ON TABLE token_usage_events IS 'LLM Token 用量计量事件表（append-only；文件时代单文件日志的多租户替代；updated_at 由 03 补齐）';
COMMENT ON COLUMN token_usage_events.id IS '事件 ID（BIGSERIAL 自增主键）';
COMMENT ON COLUMN token_usage_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN token_usage_events.org_id IS '组织维度，可为 NULL（未归属）';
COMMENT ON COLUMN token_usage_events.user_id IS '用户维度，可为 NULL（系统侧调用）';
COMMENT ON COLUMN token_usage_events.project_id IS '项目维度，可为 NULL（非项目会话）';
COMMENT ON COLUMN token_usage_events.agent_id IS '智能体 ID，可为 NULL';
COMMENT ON COLUMN token_usage_events.provider_id IS '模型提供方 ID，可为 NULL';
COMMENT ON COLUMN token_usage_events.model IS '模型标识（供按模型聚合）';
COMMENT ON COLUMN token_usage_events.prompt_tokens IS '输入 token 数';
COMMENT ON COLUMN token_usage_events.completion_tokens IS '输出 token 数';
COMMENT ON COLUMN token_usage_events.created_at IS '计量时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_usage_user ON token_usage_events (tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_usage_day_model ON token_usage_events (tenant_id, created_at, model);

-- ------------------------------------------------------------
-- 5. chats 表增量：project_id 列 + 支撑索引
--    （0002 之前的库需要；全新库由快照建表时已含）
-- ------------------------------------------------------------

ALTER TABLE chats ADD COLUMN IF NOT EXISTS project_id VARCHAR(64);

COMMENT ON COLUMN chats.project_id IS '会话所属项目 ID（XianWork 企业域，个人会话为 NULL）';

CREATE INDEX IF NOT EXISTS ix_chats_project ON chats (tenant_id, project_id);
CREATE INDEX IF NOT EXISTS ix_chats_owner_updated ON chats (tenant_id, owner_id, updated_at);

-- ------------------------------------------------------------
-- 6. Alembic 版本标记（与 alembic upgrade 至 0002_enterprise 等效）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0002_enterprise';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0002_enterprise');
    END IF;
END $$;

COMMIT;
