--
-- PostgreSQL database dump
--

\restrict bLBZejgTMEze8TjS0mU7jOHqw3W6dETeLFQ9eOQfHkkbErH0jRSgmabD7OgjJLk

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg13+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO qwenpaw;

--
-- Name: chats; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.chats (
    id character varying(64) NOT NULL,
    session_id text NOT NULL,
    user_id text NOT NULL,
    owner_id text,
    channel text DEFAULT 'console'::text NOT NULL,
    name text DEFAULT 'New Chat'::text NOT NULL,
    status text DEFAULT 'idle'::text NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    archived_at timestamp with time zone,
    source text DEFAULT 'chat'::text NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    project_id character varying(64)
);

ALTER TABLE ONLY public.chats FORCE ROW LEVEL SECURITY;


ALTER TABLE public.chats OWNER TO qwenpaw;

--
-- Name: TABLE chats; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.chats IS '会话表（镜像 ChatSpec / chats.json 行；created_at/updated_at 由应用层赋值以保持与 JSON 后端字节等价）';


--
-- Name: COLUMN chats.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.id IS '会话 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN chats.session_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.session_id IS '关联的会话状态 ID（session_states.session_id）';


--
-- Name: COLUMN chats.user_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.user_id IS '发起用户标识（文件时代字段，兼容保留）';


--
-- Name: COLUMN chats.owner_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.owner_id IS '属主用户名（M1 可信身份，RLS owner 隔离键），可为 NULL（遗留数据）';


--
-- Name: COLUMN chats.channel; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.channel IS '渠道：console（管理台）/ xian（员工端）等';


--
-- Name: COLUMN chats.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.name IS '会话名称（默认 New Chat，可重命名）';


--
-- Name: COLUMN chats.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.status IS '会话状态：idle / streaming 等';


--
-- Name: COLUMN chats.pinned; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.pinned IS '是否置顶';


--
-- Name: COLUMN chats.archived_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.archived_at IS '归档时间，可为 NULL（未归档）';


--
-- Name: COLUMN chats.source; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.source IS '会话来源：chat（普通）/ 其他入口标记';


--
-- Name: COLUMN chats.meta; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.meta IS '会话元数据（JSONB，按需扩展）';


--
-- Name: COLUMN chats.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.created_at IS '创建时间（应用层赋值，UTC，保持与 JSON 后端一致）';


--
-- Name: COLUMN chats.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.updated_at IS '更新时间（应用层赋值，UTC，保持与 JSON 后端一致）';


--
-- Name: COLUMN chats.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN chats.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.chats.project_id IS '会话所属项目 ID（XianWork 企业域，个人会话为 NULL）';


--
-- Name: department_members; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.department_members (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    department_id character varying(64) NOT NULL,
    username text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.department_members OWNER TO qwenpaw;

--
-- Name: TABLE department_members; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.department_members IS '部门成员表（部门关系的权威存储在 PG，users.json 仅保账号）';


--
-- Name: COLUMN department_members.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.department_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN department_members.department_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.department_members.department_id IS '部门 ID（联合主键成员）';


--
-- Name: COLUMN department_members.username; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.department_members.username IS '成员用户名（关联 users.json 账号，联合主键成员）';


--
-- Name: COLUMN department_members.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.department_members.created_at IS '入部门时间（DB 自动维护，UTC）';


--
-- Name: COLUMN department_members.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.department_members.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: departments; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.departments (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    parent_id character varying(64),
    name text NOT NULL,
    path text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.departments OWNER TO qwenpaw;

--
-- Name: TABLE departments; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.departments IS '部门表（树形结构，path 为部门 ID 物化路径）';


--
-- Name: COLUMN departments.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN departments.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.id IS '部门 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN departments.parent_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.parent_id IS '父部门 ID，根部门为 NULL';


--
-- Name: COLUMN departments.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.name IS '部门名称';


--
-- Name: COLUMN departments.path; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.path IS '物化路径（a/b/c 形式的部门 ID 链，子树查询走前缀匹配）';


--
-- Name: COLUMN departments.description; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.description IS '部门描述';


--
-- Name: COLUMN departments.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN departments.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.departments.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: expert_team_members; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.expert_team_members (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    team_id character varying(64) NOT NULL,
    expert_id character varying(64) NOT NULL,
    role_hint text DEFAULT ''::text NOT NULL,
    seq integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.expert_team_members OWNER TO qwenpaw;

--
-- Name: TABLE expert_team_members; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.expert_team_members IS '专家团队成员表（有序成员关系；created_at/updated_at 由 03 补齐）';


--
-- Name: COLUMN expert_team_members.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN expert_team_members.team_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.team_id IS '团队 ID（联合主键成员）';


--
-- Name: COLUMN expert_team_members.expert_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.expert_id IS '专家 ID（联合主键成员）';


--
-- Name: COLUMN expert_team_members.role_hint; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.role_hint IS '成员角色提示（供编排提示词引用）';


--
-- Name: COLUMN expert_team_members.seq; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.seq IS '成员顺序（pipeline 模式执行序，小值在前）';


--
-- Name: COLUMN expert_team_members.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN expert_team_members.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_team_members.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: expert_teams; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.expert_teams (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    mode text DEFAULT 'router'::text NOT NULL,
    router_prompt text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.expert_teams OWNER TO qwenpaw;

--
-- Name: TABLE expert_teams; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.expert_teams IS '专家团队表（轻量多智能体编排）';


--
-- Name: COLUMN expert_teams.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN expert_teams.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.id IS '团队 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN expert_teams.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.name IS '团队名称';


--
-- Name: COLUMN expert_teams.description; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.description IS '团队描述';


--
-- Name: COLUMN expert_teams.mode; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.mode IS '编排模式：router（LLM 轮选成员）/ pipeline（顺序执行、输出链式传递）';


--
-- Name: COLUMN expert_teams.router_prompt; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.router_prompt IS 'router 模式的路由提示词';


--
-- Name: COLUMN expert_teams.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.status IS '状态：draft / published / archived';


--
-- Name: COLUMN expert_teams.version; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.version IS '当前版本号';


--
-- Name: COLUMN expert_teams.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN expert_teams.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.expert_teams.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: experts; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.experts (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    name text NOT NULL,
    icon text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    agent_spec jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.experts OWNER TO qwenpaw;

--
-- Name: TABLE experts; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.experts IS '受管专家表（可发布的智能体定义）';


--
-- Name: COLUMN experts.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN experts.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.id IS '专家 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN experts.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.name IS '专家名称';


--
-- Name: COLUMN experts.icon; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.icon IS '图标标识（由应用层写入）';


--
-- Name: COLUMN experts.description; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.description IS '专家描述';


--
-- Name: COLUMN experts.agent_spec; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.agent_spec IS '与 workspace agent.json 同构的 AgentProfileConfig 快照（JSONB）';


--
-- Name: COLUMN experts.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.status IS '状态：draft（草稿）/ published（已发布）/ archived（已归档）';


--
-- Name: COLUMN experts.version; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.version IS '当前版本号（发布时自增并落 published_experts 快照）';


--
-- Name: COLUMN experts.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN experts.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.experts.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: feed_events; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.feed_events (
    id bigint NOT NULL,
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    project_id character varying(64) NOT NULL,
    actor text NOT NULL,
    kind text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.feed_events OWNER TO qwenpaw;

--
-- Name: TABLE feed_events; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.feed_events IS '项目动态流（append-only 事件表，未来按月分区的候选；updated_at 由 03 补齐）';


--
-- Name: COLUMN feed_events.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.id IS '事件 ID（BIGSERIAL 自增主键）';


--
-- Name: COLUMN feed_events.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN feed_events.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.project_id IS '所属项目 ID';


--
-- Name: COLUMN feed_events.actor; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.actor IS '触发者（用户名或 AI 标识）';


--
-- Name: COLUMN feed_events.kind; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.kind IS '事件类型：task_created / task_status / comment / ai_reply / member_joined / member_left / project_updated';


--
-- Name: COLUMN feed_events.payload; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.payload IS '事件负载（JSONB，按 kind 定义结构）';


--
-- Name: COLUMN feed_events.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.created_at IS '事件时间（DB 自动维护，UTC）';


--
-- Name: COLUMN feed_events.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.feed_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';


--
-- Name: feed_events_id_seq; Type: SEQUENCE; Schema: public; Owner: qwenpaw
--

CREATE SEQUENCE public.feed_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.feed_events_id_seq OWNER TO qwenpaw;

--
-- Name: feed_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: qwenpaw
--

ALTER SEQUENCE public.feed_events_id_seq OWNED BY public.feed_events.id;


--
-- Name: history_entries; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.history_entries (
    seq bigint NOT NULL,
    session_id text NOT NULL,
    agent_id text,
    owner_id text,
    kind text NOT NULL,
    role text,
    name text,
    content text,
    tool_call_id text,
    tool_input jsonb,
    tool_state text,
    headline text,
    blocks jsonb,
    metadata jsonb,
    created_at timestamp with time zone,
    dedup_key text,
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, COALESCE(content, ''::text))) STORED
);

ALTER TABLE ONLY public.history_entries FORCE ROW LEVEL SECURITY;


ALTER TABLE public.history_entries OWNER TO qwenpaw;

--
-- Name: TABLE history_entries; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.history_entries IS '持久化历史事件表（镜像 scroll conversation_history；append-only，seq 为全局水位；RLS owner 隔离）';


--
-- Name: COLUMN history_entries.seq; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.seq IS '全局自增序号（BIGSERIAL 主键，等价文件时代 SQLite AUTOINCREMENT 水位）';


--
-- Name: COLUMN history_entries.session_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.session_id IS '所属会话 ID';


--
-- Name: COLUMN history_entries.agent_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.agent_id IS '智能体 ID，可为 NULL';


--
-- Name: COLUMN history_entries.owner_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.owner_id IS '属主用户名（RLS owner 隔离键），可为 NULL（遗留数据）';


--
-- Name: COLUMN history_entries.kind; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.kind IS '事件类型（message / tool_call / tool_result 等）';


--
-- Name: COLUMN history_entries.role; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.role IS '消息角色（user / assistant / system 等），可为 NULL（非消息事件）';


--
-- Name: COLUMN history_entries.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.name IS '工具名或内容块名，可为 NULL';


--
-- Name: COLUMN history_entries.content; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.content IS '消息/事件正文，可为 NULL';


--
-- Name: COLUMN history_entries.tool_call_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.tool_call_id IS '工具调用关联 ID（call 与 result 配对），可为 NULL';


--
-- Name: COLUMN history_entries.tool_input; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.tool_input IS '工具调用入参（JSONB），可为 NULL';


--
-- Name: COLUMN history_entries.tool_state; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.tool_state IS '工具执行状态，可为 NULL';


--
-- Name: COLUMN history_entries.headline; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.headline IS '事件标题（列表展示用），可为 NULL';


--
-- Name: COLUMN history_entries.blocks; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.blocks IS '结构化内容块（JSONB），可为 NULL';


--
-- Name: COLUMN history_entries.metadata; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.metadata IS '事件元数据（JSONB；ORM 属性名 metadata_ 避开保留字），可为 NULL';


--
-- Name: COLUMN history_entries.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.created_at IS '事件时间（镜像文件时代 ISO 文本，UTC），可为 NULL';


--
-- Name: COLUMN history_entries.dedup_key; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.dedup_key IS '去重键（同会话内唯一，NULL 不参与去重）';


--
-- Name: COLUMN history_entries.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN history_entries.tsv; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.history_entries.tsv IS '全文检索生成列（simple 配置，CJK 友好；由 content 生成，不可写入）';


--
-- Name: history_entries_seq_seq; Type: SEQUENCE; Schema: public; Owner: qwenpaw
--

CREATE SEQUENCE public.history_entries_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.history_entries_seq_seq OWNER TO qwenpaw;

--
-- Name: history_entries_seq_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: qwenpaw
--

ALTER SEQUENCE public.history_entries_seq_seq OWNED BY public.history_entries.seq;


--
-- Name: orgs; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.orgs (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    plan text DEFAULT 'standard'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.orgs OWNER TO qwenpaw;

--
-- Name: TABLE orgs; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.orgs IS '企业组织表（租户边界，tenant_id == org.id）';


--
-- Name: COLUMN orgs.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN orgs.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.id IS '组织 ID（业务侧生成的 String(64)，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN orgs.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.name IS '组织名称';


--
-- Name: COLUMN orgs.slug; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.slug IS '组织短标识（租户内唯一，用于 URL/展示）';


--
-- Name: COLUMN orgs.plan; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.plan IS '套餐类型：standard 等';


--
-- Name: COLUMN orgs.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.status IS '组织状态：active 等';


--
-- Name: COLUMN orgs.settings; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.settings IS '组织级设置项（JSONB，按需扩展）';


--
-- Name: COLUMN orgs.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN orgs.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.orgs.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: project_automations; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.project_automations (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    project_id character varying(64) NOT NULL,
    name text NOT NULL,
    schedule text NOT NULL,
    prompt text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    cron_job_id character varying(64),
    last_run_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.project_automations OWNER TO qwenpaw;

--
-- Name: TABLE project_automations; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.project_automations IS '项目自动化表（调度权威在项目智能体 cron 管理器，本表为项目面投影）';


--
-- Name: COLUMN project_automations.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN project_automations.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.id IS '自动化任务 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN project_automations.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.project_id IS '所属项目 ID';


--
-- Name: COLUMN project_automations.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.name IS '自动化任务名称（配置面板展示）';


--
-- Name: COLUMN project_automations.schedule; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.schedule IS '调度表达式（cron 语法）';


--
-- Name: COLUMN project_automations.prompt; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.prompt IS '触发时执行的任务提示词（由应用层写入）';


--
-- Name: COLUMN project_automations.enabled; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.enabled IS '是否启用';


--
-- Name: COLUMN project_automations.cron_job_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.cron_job_id IS '项目智能体 cron 管理器中的任务 ID，可为 NULL（未注册）';


--
-- Name: COLUMN project_automations.last_run_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.last_run_at IS '最近一次执行时间，可为 NULL（从未执行）';


--
-- Name: COLUMN project_automations.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN project_automations.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_automations.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: project_bindings; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.project_bindings (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    project_id character varying(64) NOT NULL,
    kind text NOT NULL,
    ref_id text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.project_bindings OWNER TO qwenpaw;

--
-- Name: TABLE project_bindings; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.project_bindings IS '项目资源绑定表（记录项目 AI 可用的连接器/技能；注册表权威在 console 面）';


--
-- Name: COLUMN project_bindings.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN project_bindings.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.id IS '绑定 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN project_bindings.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.project_id IS '所属项目 ID';


--
-- Name: COLUMN project_bindings.kind; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.kind IS '资源类型：connector（MCP 客户端）/ skill（技能）';


--
-- Name: COLUMN project_bindings.ref_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.ref_id IS '资源在其注册表内的标识（MCP client key / skill name）';


--
-- Name: COLUMN project_bindings.enabled; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.enabled IS '是否启用（false 时项目 AI 不可使用该资源）';


--
-- Name: COLUMN project_bindings.config; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.config IS '绑定级配置（JSONB，按 kind 定义结构）';


--
-- Name: COLUMN project_bindings.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN project_bindings.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_bindings.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: project_members; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.project_members (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    project_id character varying(64) NOT NULL,
    username text NOT NULL,
    role text DEFAULT 'viewer'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.project_members OWNER TO qwenpaw;

--
-- Name: TABLE project_members; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.project_members IS '项目成员表（成员资格与项目角色）';


--
-- Name: COLUMN project_members.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN project_members.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.project_id IS '项目 ID（联合主键成员）';


--
-- Name: COLUMN project_members.username; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.username IS '成员用户名（联合主键成员）';


--
-- Name: COLUMN project_members.role; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.role IS '项目角色：owner（所有者）/ editor（可编辑）/ viewer（只读）';


--
-- Name: COLUMN project_members.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.created_at IS '加入项目时间（DB 自动维护，UTC）';


--
-- Name: COLUMN project_members.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.project_members.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: projects; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.projects (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    department_id character varying(64),
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    ai_binding jsonb DEFAULT '{}'::jsonb NOT NULL,
    template_tag text NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    instructions text
);


ALTER TABLE public.projects OWNER TO qwenpaw;

--
-- Name: TABLE projects; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.projects IS '协作项目表（instructions 列由 02_xian_extras.sql 追加）';


--
-- Name: COLUMN projects.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN projects.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.id IS '项目 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN projects.department_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.department_id IS '所属部门 ID，可为 NULL（跨部门/无部门项目）';


--
-- Name: COLUMN projects.name; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.name IS '项目名称';


--
-- Name: COLUMN projects.description; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.description IS '项目描述';


--
-- Name: COLUMN projects.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.status IS '项目状态：active 等';


--
-- Name: COLUMN projects.ai_binding; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.ai_binding IS '项目级 AI 绑定 {"kind": "expert"|"expert_team", "ref_id": ...}';


--
-- Name: COLUMN projects.template_tag; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.template_tag IS '项目模板标签（空串表示非模板项目；由应用层写入）';


--
-- Name: COLUMN projects.created_by; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.created_by IS '创建人用户名';


--
-- Name: COLUMN projects.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN projects.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: COLUMN projects.instructions; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.projects.instructions IS '项目 SOP / 系统提示词（右侧配置面板展示，注入项目共享 AI）';


--
-- Name: published_experts; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.published_experts (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    expert_id character varying(64) NOT NULL,
    version integer NOT NULL,
    spec jsonb NOT NULL,
    published_by text NOT NULL,
    published_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.published_experts OWNER TO qwenpaw;

--
-- Name: TABLE published_experts; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.published_experts IS '专家版本发布快照表（不可变、只增不删；用户面始终读最新快照；created_at/updated_at 由 03 补齐）';


--
-- Name: COLUMN published_experts.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN published_experts.expert_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.expert_id IS '专家 ID（联合主键成员）';


--
-- Name: COLUMN published_experts.version; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.version IS '发布的专家版本号（联合主键成员）';


--
-- Name: COLUMN published_experts.spec; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.spec IS '发布时的完整专家 spec（JSONB）';


--
-- Name: COLUMN published_experts.published_by; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.published_by IS '发布操作人用户名';


--
-- Name: COLUMN published_experts.published_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.published_at IS '发布时间（DB 自动维护，UTC）';


--
-- Name: COLUMN published_experts.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN published_experts.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.published_experts.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: session_states; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.session_states (
    channel text DEFAULT ''::text NOT NULL,
    owner_id text DEFAULT ''::text NOT NULL,
    session_id text NOT NULL,
    state jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL
);

ALTER TABLE ONLY public.session_states FORCE ROW LEVEL SECURITY;


ALTER TABLE public.session_states OWNER TO qwenpaw;

--
-- Name: TABLE session_states; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.session_states IS '会话状态表（镜像 *.json 会话文件，复合主键即文件名身份）';


--
-- Name: COLUMN session_states.channel; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.channel IS '渠道（复合主键成员，文件时代文件名的一部分）';


--
-- Name: COLUMN session_states.owner_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.owner_id IS '属主用户名（复合主键成员，RLS owner 隔离键）';


--
-- Name: COLUMN session_states.session_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.session_id IS '会话 ID（复合主键成员）';


--
-- Name: COLUMN session_states.state; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.state IS '会话状态文档（JSONB，智能体运行时状态）';


--
-- Name: COLUMN session_states.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.created_at IS '创建时间（应用层赋值，UTC）';


--
-- Name: COLUMN session_states.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.updated_at IS '更新时间（应用层赋值，UTC）';


--
-- Name: COLUMN session_states.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.session_states.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.tasks (
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    id character varying(64) NOT NULL,
    project_id character varying(64) NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'todo'::text NOT NULL,
    assignee text,
    creator text NOT NULL,
    chat_id character varying(64),
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.tasks OWNER TO qwenpaw;

--
-- Name: TABLE tasks; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.tasks IS '看板任务表（项目内四列看板）';


--
-- Name: COLUMN tasks.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN tasks.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.id IS '任务 ID（业务侧生成，与 tenant_id 组成联合主键）';


--
-- Name: COLUMN tasks.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.project_id IS '所属项目 ID';


--
-- Name: COLUMN tasks.title; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.title IS '任务标题';


--
-- Name: COLUMN tasks.description; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.description IS '任务描述';


--
-- Name: COLUMN tasks.status; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.status IS '看板列状态：todo（待办）/ doing（进行中）/ paused（暂停）/ done（完成）';


--
-- Name: COLUMN tasks.assignee; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.assignee IS '经办人用户名，可为 NULL（未认领）';


--
-- Name: COLUMN tasks.creator; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.creator IS '创建人用户名';


--
-- Name: COLUMN tasks.chat_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.chat_id IS '弱引用 ChatSpec.id（任务由 AI 会话创建/执行时关联），可为 NULL';


--
-- Name: COLUMN tasks.sort_order; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.sort_order IS '看板列内排序值（小值在前，由应用层维护）';


--
-- Name: COLUMN tasks.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.created_at IS '创建时间（DB 自动维护，UTC）';


--
-- Name: COLUMN tasks.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.tasks.updated_at IS '更新时间（DB 自动维护，UTC）';


--
-- Name: token_usage_events; Type: TABLE; Schema: public; Owner: qwenpaw
--

CREATE TABLE public.token_usage_events (
    id bigint NOT NULL,
    tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
    org_id character varying(64),
    user_id text,
    project_id character varying(64),
    agent_id text,
    provider_id text,
    model text,
    prompt_tokens integer DEFAULT 0 NOT NULL,
    completion_tokens integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.token_usage_events OWNER TO qwenpaw;

--
-- Name: TABLE token_usage_events; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON TABLE public.token_usage_events IS 'LLM Token 用量计量事件表（append-only；文件时代单文件日志的多租户替代；updated_at 由 03 补齐）';


--
-- Name: COLUMN token_usage_events.id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.id IS '事件 ID（BIGSERIAL 自增主键）';


--
-- Name: COLUMN token_usage_events.tenant_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';


--
-- Name: COLUMN token_usage_events.org_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.org_id IS '组织维度，可为 NULL（未归属）';


--
-- Name: COLUMN token_usage_events.user_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.user_id IS '用户维度，可为 NULL（系统侧调用）';


--
-- Name: COLUMN token_usage_events.project_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.project_id IS '项目维度，可为 NULL（非项目会话）';


--
-- Name: COLUMN token_usage_events.agent_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.agent_id IS '智能体 ID，可为 NULL';


--
-- Name: COLUMN token_usage_events.provider_id; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.provider_id IS '模型提供方 ID，可为 NULL';


--
-- Name: COLUMN token_usage_events.model; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.model IS '模型标识（供按模型聚合）';


--
-- Name: COLUMN token_usage_events.prompt_tokens; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.prompt_tokens IS '输入 token 数';


--
-- Name: COLUMN token_usage_events.completion_tokens; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.completion_tokens IS '输出 token 数';


--
-- Name: COLUMN token_usage_events.created_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.created_at IS '计量时间（DB 自动维护，UTC）';


--
-- Name: COLUMN token_usage_events.updated_at; Type: COMMENT; Schema: public; Owner: qwenpaw
--

COMMENT ON COLUMN public.token_usage_events.updated_at IS '更新时间（append-only 表，恒为插入时刻，UTC）';


--
-- Name: token_usage_events_id_seq; Type: SEQUENCE; Schema: public; Owner: qwenpaw
--

CREATE SEQUENCE public.token_usage_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.token_usage_events_id_seq OWNER TO qwenpaw;

--
-- Name: token_usage_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: qwenpaw
--

ALTER SEQUENCE public.token_usage_events_id_seq OWNED BY public.token_usage_events.id;


--
-- Name: feed_events id; Type: DEFAULT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.feed_events ALTER COLUMN id SET DEFAULT nextval('public.feed_events_id_seq'::regclass);


--
-- Name: history_entries seq; Type: DEFAULT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.history_entries ALTER COLUMN seq SET DEFAULT nextval('public.history_entries_seq_seq'::regclass);


--
-- Name: token_usage_events id; Type: DEFAULT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.token_usage_events ALTER COLUMN id SET DEFAULT nextval('public.token_usage_events_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.alembic_version (version_num) FROM stdin;
0004_table_timestamps
\.


--
-- Data for Name: chats; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.chats (id, session_id, user_id, owner_id, channel, name, status, pinned, archived_at, source, meta, created_at, updated_at, tenant_id, project_id) FROM stdin;
c-alice	s1	alice	alice	console	A	idle	f	\N	chat	{}	2026-08-13 11:25:10.395332+00	2026-08-13 11:25:10.395332+00	default	\N
c-bob	s2	bob	bob	console	B	idle	f	\N	chat	{}	2026-08-13 11:25:10.395332+00	2026-08-13 11:25:10.395332+00	default	\N
c-legacy	s3	carol	\N	console	L	idle	f	\N	chat	{}	2026-08-13 11:25:10.395332+00	2026-08-13 11:25:10.395332+00	default	\N
c-new	s9	alice	alice	console	X	idle	f	\N	chat	{}	2026-08-13 11:25:10.437925+00	2026-08-13 11:25:10.437925+00	default	\N
\.


--
-- Data for Name: department_members; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.department_members (tenant_id, department_id, username, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: departments; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.departments (tenant_id, id, parent_id, name, path, description, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: expert_team_members; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.expert_team_members (tenant_id, team_id, expert_id, role_hint, seq, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: expert_teams; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.expert_teams (tenant_id, id, name, description, mode, router_prompt, status, version, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: experts; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.experts (tenant_id, id, name, icon, description, agent_spec, status, version, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: feed_events; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.feed_events (id, tenant_id, project_id, actor, kind, payload, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: history_entries; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.history_entries (seq, session_id, agent_id, owner_id, kind, role, name, content, tool_call_id, tool_input, tool_state, headline, blocks, metadata, created_at, dedup_key, tenant_id) FROM stdin;
103	console:dm	a1	alice	context_msg	user	\N	deploy the tank report	\N	\N	\N	\N	\N	\N	2026-08-13 11:25:09.339103+00	a-user-1	default
104	console:dm	a1	alice	context_msg	assistant	\N	tank report deployed to prod	\N	\N	\N	\N	\N	\N	2026-08-13 11:25:09.443469+00	a-asst-1	default
105	console:dm-bob	a1	bob	context_msg	user	\N	my aquarium setup notes	\N	\N	\N	\N	\N	\N	2026-08-13 11:25:09.455046+00	b-user-1	default
106	console:dm	a1	alice	context_msg	user	\N	current in-progress request	\N	\N	\N	\N	\N	\N	2026-08-13 11:25:09.467186+00	a-active-1	default
\.


--
-- Data for Name: orgs; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.orgs (tenant_id, id, name, slug, plan, status, settings, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: project_automations; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.project_automations (tenant_id, id, project_id, name, schedule, prompt, enabled, cron_job_id, last_run_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: project_bindings; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.project_bindings (tenant_id, id, project_id, kind, ref_id, enabled, config, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: project_members; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.project_members (tenant_id, project_id, username, role, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: projects; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.projects (tenant_id, id, department_id, name, description, status, ai_binding, template_tag, created_by, created_at, updated_at, instructions) FROM stdin;
\.


--
-- Data for Name: published_experts; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.published_experts (tenant_id, expert_id, version, spec, published_by, published_at, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: session_states; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.session_states (channel, owner_id, session_id, state, created_at, updated_at, tenant_id) FROM stdin;
	alice	s1	{"state": {"owner": "alice"}}	2026-08-13 10:59:01.288154+00	2026-08-13 10:59:01.288154+00	default
	bob	s1	{"state": {"owner": "bob"}}	2026-08-13 10:59:01.288685+00	2026-08-13 10:59:01.288685+00	default
\.


--
-- Data for Name: tasks; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.tasks (tenant_id, id, project_id, title, description, status, assignee, creator, chat_id, sort_order, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: token_usage_events; Type: TABLE DATA; Schema: public; Owner: qwenpaw
--

COPY public.token_usage_events (id, tenant_id, org_id, user_id, project_id, agent_id, provider_id, model, prompt_tokens, completion_tokens, created_at, updated_at) FROM stdin;
\.


--
-- Name: feed_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: qwenpaw
--

SELECT pg_catalog.setval('public.feed_events_id_seq', 1, false);


--
-- Name: history_entries_seq_seq; Type: SEQUENCE SET; Schema: public; Owner: qwenpaw
--

SELECT pg_catalog.setval('public.history_entries_seq_seq', 106, true);


--
-- Name: token_usage_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: qwenpaw
--

SELECT pg_catalog.setval('public.token_usage_events_id_seq', 1, false);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: feed_events feed_events_pkey; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.feed_events
    ADD CONSTRAINT feed_events_pkey PRIMARY KEY (id);


--
-- Name: history_entries history_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.history_entries
    ADD CONSTRAINT history_entries_pkey PRIMARY KEY (seq);


--
-- Name: chats pk_chats; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.chats
    ADD CONSTRAINT pk_chats PRIMARY KEY (tenant_id, id);


--
-- Name: department_members pk_department_members; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.department_members
    ADD CONSTRAINT pk_department_members PRIMARY KEY (tenant_id, department_id, username);


--
-- Name: departments pk_departments; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT pk_departments PRIMARY KEY (tenant_id, id);


--
-- Name: expert_team_members pk_expert_team_members; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.expert_team_members
    ADD CONSTRAINT pk_expert_team_members PRIMARY KEY (tenant_id, team_id, expert_id);


--
-- Name: expert_teams pk_expert_teams; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.expert_teams
    ADD CONSTRAINT pk_expert_teams PRIMARY KEY (tenant_id, id);


--
-- Name: experts pk_experts; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.experts
    ADD CONSTRAINT pk_experts PRIMARY KEY (tenant_id, id);


--
-- Name: orgs pk_orgs; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.orgs
    ADD CONSTRAINT pk_orgs PRIMARY KEY (tenant_id, id);


--
-- Name: project_automations pk_project_automations; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.project_automations
    ADD CONSTRAINT pk_project_automations PRIMARY KEY (tenant_id, id);


--
-- Name: project_bindings pk_project_bindings; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.project_bindings
    ADD CONSTRAINT pk_project_bindings PRIMARY KEY (tenant_id, id);


--
-- Name: project_members pk_project_members; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT pk_project_members PRIMARY KEY (tenant_id, project_id, username);


--
-- Name: projects pk_projects; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT pk_projects PRIMARY KEY (tenant_id, id);


--
-- Name: published_experts pk_published_experts; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.published_experts
    ADD CONSTRAINT pk_published_experts PRIMARY KEY (tenant_id, expert_id, version);


--
-- Name: session_states pk_session_states; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.session_states
    ADD CONSTRAINT pk_session_states PRIMARY KEY (tenant_id, channel, owner_id, session_id);


--
-- Name: tasks pk_tasks; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT pk_tasks PRIMARY KEY (tenant_id, id);


--
-- Name: token_usage_events token_usage_events_pkey; Type: CONSTRAINT; Schema: public; Owner: qwenpaw
--

ALTER TABLE ONLY public.token_usage_events
    ADD CONSTRAINT token_usage_events_pkey PRIMARY KEY (id);


--
-- Name: ix_chats_owner; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_chats_owner ON public.chats USING btree (tenant_id, owner_id);


--
-- Name: ix_chats_owner_updated; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_chats_owner_updated ON public.chats USING btree (tenant_id, owner_id, updated_at);


--
-- Name: ix_chats_project; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_chats_project ON public.chats USING btree (tenant_id, project_id);


--
-- Name: ix_chats_session; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_chats_session ON public.chats USING btree (tenant_id, session_id, channel, user_id);


--
-- Name: ix_department_members_user; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_department_members_user ON public.department_members USING btree (tenant_id, username);


--
-- Name: ix_departments_parent; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_departments_parent ON public.departments USING btree (tenant_id, parent_id);


--
-- Name: ix_departments_path; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_departments_path ON public.departments USING btree (tenant_id, path);


--
-- Name: ix_expert_team_members_expert; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_expert_team_members_expert ON public.expert_team_members USING btree (tenant_id, expert_id);


--
-- Name: ix_expert_teams_status; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_expert_teams_status ON public.expert_teams USING btree (tenant_id, status);


--
-- Name: ix_experts_status; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_experts_status ON public.experts USING btree (tenant_id, status);


--
-- Name: ix_feed_project; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_feed_project ON public.feed_events USING btree (tenant_id, project_id, id DESC);


--
-- Name: ix_history_agent; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_agent ON public.history_entries USING btree (tenant_id, agent_id);


--
-- Name: ix_history_created_at; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_created_at ON public.history_entries USING btree (tenant_id, created_at);


--
-- Name: ix_history_kind; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_kind ON public.history_entries USING btree (tenant_id, kind);


--
-- Name: ix_history_owner; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_owner ON public.history_entries USING btree (tenant_id, owner_id);


--
-- Name: ix_history_session; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_session ON public.history_entries USING btree (tenant_id, session_id);


--
-- Name: ix_history_tsv; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_history_tsv ON public.history_entries USING gin (tsv);


--
-- Name: ix_project_automations_project; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_project_automations_project ON public.project_automations USING btree (tenant_id, project_id);


--
-- Name: ix_project_members_user; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_project_members_user ON public.project_members USING btree (tenant_id, username);


--
-- Name: ix_projects_department; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_projects_department ON public.projects USING btree (tenant_id, department_id);


--
-- Name: ix_projects_status; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_projects_status ON public.projects USING btree (tenant_id, status);


--
-- Name: ix_tasks_assignee; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_tasks_assignee ON public.tasks USING btree (tenant_id, assignee, status);


--
-- Name: ix_tasks_board; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_tasks_board ON public.tasks USING btree (tenant_id, project_id, status, updated_at);


--
-- Name: ix_usage_day_model; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_usage_day_model ON public.token_usage_events USING btree (tenant_id, created_at, model);


--
-- Name: ix_usage_user; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE INDEX ix_usage_user ON public.token_usage_events USING btree (tenant_id, user_id, created_at);


--
-- Name: ux_history_dedup; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE UNIQUE INDEX ux_history_dedup ON public.history_entries USING btree (tenant_id, session_id, dedup_key) WHERE (dedup_key IS NOT NULL);


--
-- Name: ux_orgs_slug; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE UNIQUE INDEX ux_orgs_slug ON public.orgs USING btree (tenant_id, slug);


--
-- Name: ux_project_bindings; Type: INDEX; Schema: public; Owner: qwenpaw
--

CREATE UNIQUE INDEX ux_project_bindings ON public.project_bindings USING btree (tenant_id, project_id, kind, ref_id);


--
-- Name: chats; Type: ROW SECURITY; Schema: public; Owner: qwenpaw
--

ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;

--
-- Name: history_entries; Type: ROW SECURITY; Schema: public; Owner: qwenpaw
--

ALTER TABLE public.history_entries ENABLE ROW LEVEL SECURITY;

--
-- Name: chats owner_isolation; Type: POLICY; Schema: public; Owner: qwenpaw
--

CREATE POLICY owner_isolation ON public.chats USING (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true)))) WITH CHECK (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true))));


--
-- Name: history_entries owner_isolation; Type: POLICY; Schema: public; Owner: qwenpaw
--

CREATE POLICY owner_isolation ON public.history_entries USING (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true)))) WITH CHECK (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true))));


--
-- Name: session_states owner_isolation; Type: POLICY; Schema: public; Owner: qwenpaw
--

CREATE POLICY owner_isolation ON public.session_states USING (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true)))) WITH CHECK (((current_setting('app.current_owner'::text, true) IS NULL) OR (current_setting('app.current_owner'::text, true) = ''::text) OR (owner_id IS NULL) OR (owner_id = current_setting('app.current_owner'::text, true))));


--
-- Name: session_states; Type: ROW SECURITY; Schema: public; Owner: qwenpaw
--

ALTER TABLE public.session_states ENABLE ROW LEVEL SECURITY;

--
-- Name: TABLE chats; Type: ACL; Schema: public; Owner: qwenpaw
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.chats TO rls_probe;


--
-- PostgreSQL database dump complete
--

\unrestrict bLBZejgTMEze8TjS0mU7jOHqw3W6dETeLFQ9eOQfHkkbErH0jRSgmabD7OgjJLk

