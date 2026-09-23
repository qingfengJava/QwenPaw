-- ============================================================
-- 变更说明: M2 存储三表字段注释补齐 —— chats / session_states /
--           history_entries 由 0001 时期 alembic metadata 建表，
--           库内从未写入字段备注；按规范为全部字段（含 tsv 生成列）
--           补 COMMENT ON，并补表级注释
-- 变更时间: 2026-08-15
-- 变更人:   清风
-- 适用环境: test / prod（PostgreSQL 14+）
-- 对应迁移: 无 schema 变更（仅注释，不产生新的 alembic 版本；
--           注释内容与 0004 head 快照一致）
-- 快照同步: 本文件内容已包含在 ../../test.sql 与 ../../prod.sql
--           （快照自始含这些 COMMENT ON，本文件为既有库增量补齐）
-- 执行方式: psql 单事务执行；COMMENT ON 天然幂等，可重复执行
-- 依赖说明: 需先执行 01_enterprise_schema.sql（三张表已存在）
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. chats：表注释 + 15 个字段注释
-- ------------------------------------------------------------

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

-- ------------------------------------------------------------
-- 2. session_states：表注释 + 7 个字段注释
-- ------------------------------------------------------------

COMMENT ON TABLE session_states IS '会话状态表（镜像 *.json 会话文件，复合主键即文件名身份）';
COMMENT ON COLUMN session_states.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN session_states.channel IS '渠道（复合主键成员，文件时代文件名的一部分）';
COMMENT ON COLUMN session_states.owner_id IS '属主用户名（复合主键成员，RLS owner 隔离键）';
COMMENT ON COLUMN session_states.session_id IS '会话 ID（复合主键成员）';
COMMENT ON COLUMN session_states.state IS '会话状态文档（JSONB，智能体运行时状态）';
COMMENT ON COLUMN session_states.created_at IS '创建时间（应用层赋值，UTC）';
COMMENT ON COLUMN session_states.updated_at IS '更新时间（应用层赋值，UTC）';

-- ------------------------------------------------------------
-- 3. history_entries：表注释 + 18 个字段注释（含 tsv 生成列）
-- ------------------------------------------------------------

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

COMMIT;
