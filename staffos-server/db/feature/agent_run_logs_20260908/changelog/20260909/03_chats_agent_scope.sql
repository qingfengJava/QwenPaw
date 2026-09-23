-- [变更说明] chats/session_states 增加 agent_id 维度（数字员工会话隔离）
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
--
-- 背景：JSON 后端时代每个 agent workspace 独立 chats.json/sessions 目录
-- 天然隔离；切到 PG 后端后所有员工共表，缺 agent 维度导致 list_chats
-- 全租户泄漏（详情页聊天面板显示其他员工的会话）。
-- 存量行归属由 python -m qwenpaw.db.backfill_chat_agent 清洗。

-- chats：归属智能体列 + 复合索引
ALTER TABLE chats ADD COLUMN IF NOT EXISTS agent_id
VARCHAR(128) NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS ix_chats_tenant_agent
ON chats (tenant_id, agent_id);
COMMENT ON COLUMN chats.agent_id IS
'归属智能体标识（数字员工会话隔离；历史行由 backfill_chat_agent 修正）';

-- session_states：归属智能体列 + 主键扩展（同用户同 session_id 不再跨员工互覆）
ALTER TABLE session_states ADD COLUMN IF NOT EXISTS agent_id
VARCHAR(128) NOT NULL DEFAULT 'default';
ALTER TABLE session_states DROP CONSTRAINT IF EXISTS pk_session_states;
ALTER TABLE session_states ADD CONSTRAINT pk_session_states
PRIMARY KEY (tenant_id, agent_id, channel, owner_id, session_id);
COMMENT ON COLUMN session_states.agent_id IS
'归属智能体标识（数字员工会话状态隔离）';
