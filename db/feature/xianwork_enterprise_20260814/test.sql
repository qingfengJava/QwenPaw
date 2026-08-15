-- ============================================================
-- 变更说明: XianWork 企业数字员工平台 test 环境全量 schema 快照
--           （0001_initial + 0002_enterprise + 0003_xian_extras
--            + 0004_table_timestamps）
--           覆盖：M2 存储三表（chats / session_states / history_entries，
--           含 tsv 生成列与 owner 隔离 RLS）、12 张企业表、
--           project_bindings / project_automations、
--           projects.instructions、chats.project_id、
--           全部业务表的 created_at / updated_at 时间戳规范
-- 变更时间: 2026-08-15
-- 变更人:   清风
-- 适用环境: test（PostgreSQL 14+，从零建库 / 校验既有库）
-- 对应迁移: alembic head = 0004_table_timestamps
-- 快照同步: 与 changelog/20260814/01+02+03 增量内容一致（本文件为全量形态）
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 0. Alembic 版本表
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

COMMENT ON TABLE alembic_version IS 'Alembic 迁移版本表（单行，记录当前 schema 版本）';

-- ------------------------------------------------------------
-- 1. M2 存储三表（0001_initial）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chats (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    session_id  TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    owner_id    TEXT,
    channel     TEXT NOT NULL DEFAULT 'console',
    name        TEXT NOT NULL DEFAULT 'New Chat',
    status      TEXT NOT NULL DEFAULT 'idle',
    pinned      BOOLEAN NOT NULL DEFAULT false,
    archived_at TIMESTAMP WITH TIME ZONE,
    source      TEXT NOT NULL DEFAULT 'chat',
    project_id  VARCHAR(64),
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_chats PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE chats IS '会话表（镜像 ChatSpec / chats.json 行；created_at/updated_at 由应用层赋值以保持与 JSON 后端字节等价）';
COMMENT ON COLUMN chats.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN chats.id IS '会话 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN chats.session_id IS '关联的会话状态 ID（session_states.session_id）';
COMMENT ON COLUMN chats.user_id IS '发起用户标识（文件时代字段，兼容保留）';
COMMENT ON COLUMN chats.owner_id IS '属主用户名（M1 可信身份，RLS owner 隔离键），可为 NULL（遗留数据）';
COMMENT ON COLUMN chats.channel IS '渠道：console（管理台）/ xian（员工端）等';
COMMENT ON COLUMN chats.name IS '会话名称（默认 New Chat，可重命名）';
COMMENT ON COLUMN chats.status IS '会话状态：idle / streaming 等';
COMMENT ON COLUMN chats.pinned IS '是否置顶';
COMMENT ON COLUMN chats.archived_at IS '归档时间，可为 NULL（未归档）';
COMMENT ON COLUMN chats.source IS '会话来源：chat（普通）/ 其他入口标记';
COMMENT ON COLUMN chats.project_id IS '会话所属项目 ID（XianWork 企业域，个人会话为 NULL）';
COMMENT ON COLUMN chats.meta IS '会话元数据（JSONB，按需扩展）';
COMMENT ON COLUMN chats.created_at IS '创建时间（应用层赋值，UTC，保持与 JSON 后端一致）';
COMMENT ON COLUMN chats.updated_at IS '更新时间（应用层赋值，UTC，保持与 JSON 后端一致）';

CREATE INDEX IF NOT EXISTS ix_chats_owner ON chats (tenant_id, owner_id);
CREATE INDEX IF NOT EXISTS ix_chats_owner_updated ON chats (tenant_id, owner_id, updated_at);
CREATE INDEX IF NOT EXISTS ix_chats_project ON chats (tenant_id, project_id);
CREATE INDEX IF NOT EXISTS ix_chats_session ON chats (tenant_id, session_id, channel, user_id);

CREATE TABLE IF NOT EXISTS session_states (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    channel    TEXT NOT NULL DEFAULT '',
    owner_id   TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL,
    state      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_session_states PRIMARY KEY (tenant_id, channel, owner_id, session_id)
);

COMMENT ON TABLE session_states IS '会话状态表（镜像 *.json 会话文件，复合主键即文件名身份）';
COMMENT ON COLUMN session_states.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN session_states.channel IS '渠道（复合主键成员，文件时代文件名的一部分）';
COMMENT ON COLUMN session_states.owner_id IS '属主用户名（复合主键成员，RLS owner 隔离键）';
COMMENT ON COLUMN session_states.session_id IS '会话 ID（复合主键成员）';
COMMENT ON COLUMN session_states.state IS '会话状态文档（JSONB，智能体运行时状态）';
COMMENT ON COLUMN session_states.created_at IS '创建时间（应用层赋值，UTC）';
COMMENT ON COLUMN session_states.updated_at IS '更新时间（应用层赋值，UTC）';

CREATE TABLE IF NOT EXISTS history_entries (
    seq          BIGSERIAL NOT NULL,
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    session_id   TEXT NOT NULL,
    agent_id     TEXT,
    owner_id     TEXT,
    kind         TEXT NOT NULL,
    role         TEXT,
    name         TEXT,
    content      TEXT,
    tool_call_id TEXT,
    tool_input   JSONB,
    tool_state   TEXT,
    headline     TEXT,
    blocks       JSONB,
    metadata     JSONB,
    created_at   TIMESTAMP WITH TIME ZONE,
    dedup_key    TEXT,
    PRIMARY KEY (seq)
);

COMMENT ON TABLE history_entries IS '持久化历史事件表（镜像 scroll conversation_history；append-only，seq 为全局水位；RLS owner 隔离）';
COMMENT ON COLUMN history_entries.seq IS '全局自增序号（BIGSERIAL 主键，等价文件时代 SQLite AUTOINCREMENT 水位）';
COMMENT ON COLUMN history_entries.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN history_entries.session_id IS '所属会话 ID';
COMMENT ON COLUMN history_entries.agent_id IS '智能体 ID，可为 NULL';
COMMENT ON COLUMN history_entries.owner_id IS '属主用户名（RLS owner 隔离键），可为 NULL（遗留数据）';
COMMENT ON COLUMN history_entries.kind IS '事件类型（message / tool_call / tool_result 等）';
COMMENT ON COLUMN history_entries.role IS '消息角色（user / assistant / system 等），可为 NULL（非消息事件）';
COMMENT ON COLUMN history_entries.name IS '工具名或内容块名，可为 NULL';
COMMENT ON COLUMN history_entries.content IS '消息/事件正文，可为 NULL';
COMMENT ON COLUMN history_entries.tool_call_id IS '工具调用关联 ID（call 与 result 配对），可为 NULL';
COMMENT ON COLUMN history_entries.tool_input IS '工具调用入参（JSONB），可为 NULL';
COMMENT ON COLUMN history_entries.tool_state IS '工具执行状态，可为 NULL';
COMMENT ON COLUMN history_entries.headline IS '事件标题（列表展示用），可为 NULL';
COMMENT ON COLUMN history_entries.blocks IS '结构化内容块（JSONB），可为 NULL';
COMMENT ON COLUMN history_entries.metadata IS '事件元数据（JSONB；ORM 属性名 metadata_ 避开保留字），可为 NULL';
COMMENT ON COLUMN history_entries.created_at IS '事件时间（镜像文件时代 ISO 文本，UTC），可为 NULL';
COMMENT ON COLUMN history_entries.dedup_key IS '去重键（同会话内唯一，NULL 不参与去重）';
COMMENT ON COLUMN history_entries.tsv IS '全文检索生成列（simple 配置，CJK 友好；由 content 生成，不可写入）';

CREATE INDEX IF NOT EXISTS ix_history_session ON history_entries (tenant_id, session_id);
CREATE INDEX IF NOT EXISTS ix_history_agent ON history_entries (tenant_id, agent_id);
CREATE INDEX IF NOT EXISTS ix_history_owner ON history_entries (tenant_id, owner_id);
CREATE INDEX IF NOT EXISTS ix_history_kind ON history_entries (tenant_id, kind);
CREATE INDEX IF NOT EXISTS ix_history_created_at ON history_entries (tenant_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_history_dedup
    ON history_entries (tenant_id, session_id, dedup_key)
    WHERE dedup_key IS NOT NULL;

-- tsvector 全文检索列（替代 SQLite FTS5）
ALTER TABLE history_entries
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(content, ''))
    ) STORED;

CREATE INDEX IF NOT EXISTS ix_history_tsv ON history_entries USING GIN (tsv);

-- Owner 隔离 RLS（PERMISSIVE 灰度策略；无 DROP 语句的幂等形态）
ALTER TABLE chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE chats FORCE ROW LEVEL SECURITY;
ALTER TABLE session_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_states FORCE ROW LEVEL SECURITY;
ALTER TABLE history_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE history_entries FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
    t TEXT;
    predicate TEXT :=
        'current_setting(''app.current_owner'', true) IS NULL ' ||
        'OR current_setting(''app.current_owner'', true) = '''' ' ||
        'OR owner_id IS NULL ' ||
        'OR owner_id = current_setting(''app.current_owner'', true)';
BEGIN
    FOREACH t IN ARRAY ARRAY['chats', 'session_states', 'history_entries'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t AND policyname = 'owner_isolation'
        ) THEN
            EXECUTE format(
                'CREATE POLICY owner_isolation ON %I AS PERMISSIVE FOR ALL USING (%s) WITH CHECK (%s)',
                t, predicate, predicate
            );
        END IF;
    END LOOP;
END $$;

-- ------------------------------------------------------------
-- 2. 组织与部门（0002_enterprise）
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
-- 3. 项目与任务（0002_enterprise + 0003 instructions）
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
    instructions  TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_projects PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE projects IS '协作项目表';
COMMENT ON COLUMN projects.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN projects.id IS '项目 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN projects.department_id IS '所属部门 ID，可为 NULL（跨部门/无部门项目）';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.description IS '项目描述';
COMMENT ON COLUMN projects.status IS '项目状态：active 等';
COMMENT ON COLUMN projects.ai_binding IS '项目级 AI 绑定 {"kind": "expert"|"expert_team", "ref_id": ...}';
COMMENT ON COLUMN projects.template_tag IS '项目模板标签（空串表示非模板项目；由应用层写入）';
COMMENT ON COLUMN projects.created_by IS '创建人用户名';
COMMENT ON COLUMN projects.instructions IS '项目 SOP / 系统提示词（右侧配置面板展示，注入项目共享 AI）';
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
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

COMMENT ON TABLE feed_events IS '项目动态流（append-only 事件表，未来按月分区的候选）';
COMMENT ON COLUMN feed_events.id IS '事件 ID（BIGSERIAL 自增主键）';
COMMENT ON COLUMN feed_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN feed_events.project_id IS '所属项目 ID';
COMMENT ON COLUMN feed_events.actor IS '触发者（用户名或 AI 标识）';
COMMENT ON COLUMN feed_events.kind IS '事件类型：task_created / task_status / comment / ai_reply / member_joined / member_left / project_updated';
COMMENT ON COLUMN feed_events.payload IS '事件负载（JSONB，按 kind 定义结构）';
COMMENT ON COLUMN feed_events.created_at IS '事件时间（DB 自动维护，UTC）';
COMMENT ON COLUMN feed_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';

CREATE INDEX IF NOT EXISTS ix_feed_project ON feed_events (tenant_id, project_id, id DESC);

-- ------------------------------------------------------------
-- 4. 专家与专家团队（0002_enterprise + 0004 时间戳）
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
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    team_id    VARCHAR(64) NOT NULL,
    expert_id  VARCHAR(64) NOT NULL,
    role_hint  TEXT NOT NULL DEFAULT '',
    seq        INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_team_members PRIMARY KEY (tenant_id, team_id, expert_id)
);

COMMENT ON TABLE expert_team_members IS '专家团队成员表（有序成员关系）';
COMMENT ON COLUMN expert_team_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN expert_team_members.team_id IS '团队 ID（联合主键成员）';
COMMENT ON COLUMN expert_team_members.expert_id IS '专家 ID（联合主键成员）';
COMMENT ON COLUMN expert_team_members.role_hint IS '成员角色提示（供编排提示词引用）';
COMMENT ON COLUMN expert_team_members.seq IS '成员顺序（pipeline 模式执行序，小值在前）';
COMMENT ON COLUMN expert_team_members.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN expert_team_members.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE INDEX IF NOT EXISTS ix_expert_team_members_expert ON expert_team_members (tenant_id, expert_id);

CREATE TABLE IF NOT EXISTS published_experts (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    expert_id    VARCHAR(64) NOT NULL,
    version      INTEGER NOT NULL,
    spec         JSONB NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_published_experts PRIMARY KEY (tenant_id, expert_id, version)
);

COMMENT ON TABLE published_experts IS '专家版本发布快照表（不可变、只增不删；用户面始终读最新快照）';
COMMENT ON COLUMN published_experts.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN published_experts.expert_id IS '专家 ID（联合主键成员）';
COMMENT ON COLUMN published_experts.version IS '发布的专家版本号（联合主键成员）';
COMMENT ON COLUMN published_experts.spec IS '发布时的完整专家 spec（JSONB）';
COMMENT ON COLUMN published_experts.published_by IS '发布操作人用户名';
COMMENT ON COLUMN published_experts.published_at IS '发布时间（DB 自动维护，UTC，业务语义列）';
COMMENT ON COLUMN published_experts.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN published_experts.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 5. Token 计量（0002_enterprise + 0004 时间戳）
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
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);

COMMENT ON TABLE token_usage_events IS 'LLM Token 用量计量事件表（append-only；文件时代单文件日志的多租户替代）';
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
COMMENT ON COLUMN token_usage_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';

CREATE INDEX IF NOT EXISTS ix_usage_user ON token_usage_events (tenant_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_usage_day_model ON token_usage_events (tenant_id, created_at, model);

-- ------------------------------------------------------------
-- 6. 项目扩展（0003_xian_extras）
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
-- 7. Alembic 版本标记（head）
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0004_table_timestamps';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0004_table_timestamps');
    END IF;
END $$;

COMMIT;
