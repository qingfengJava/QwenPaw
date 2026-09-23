-- [变更说明] 运行日志 Span 化：agent_runs 列表表 + agent_run_spans 执行树表
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
--
-- 背景：运行日志原为「inbox_trace 消息快照 + run_logs/index-*.jsonl 文件
-- 索引」，前端执行树只能从消息流猜测语义。升级为 span 级采集
-- （SpanRecorderMiddleware 在 on_system_prompt/on_model_call/on_acting/
-- on_reply 边界埋点）+ PG 双表存储。无 PG 部署继续走文件路径。
-- alembic twin: 0017_run_log_spans

-- 运行日志列表行（替代 run_logs/index-*.jsonl）
CREATE TABLE IF NOT EXISTS agent_runs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    run_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    display_name VARCHAR(128),
    session_id VARCHAR(128),
    root_session_id VARCHAR(128),
    chat_id VARCHAR(128),
    user_id VARCHAR(128),
    channel VARCHAR(64),
    source VARCHAR(32),
    environment VARCHAR(16),
    query_preview TEXT,
    status VARCHAR(16) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms INTEGER,
    total_tokens INTEGER,
    model VARCHAR(128),
    version VARCHAR(64),
    app_version VARCHAR(64),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_runs PRIMARY KEY (run_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_started
ON agent_runs (tenant_id, agent_id, started_at);

-- 已按初始 0017 建库的环境补列（幂等）
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS display_name VARCHAR(128);

COMMENT ON TABLE agent_runs IS
'Agent 运行日志列表行（替代 run_logs/index-*.jsonl 文件索引）';
COMMENT ON COLUMN agent_runs.status IS '状态: running, success, failed';
COMMENT ON COLUMN agent_runs.display_name IS
'智能体可读名称（AgentProfileConfig.name，展示用；空则前端回退 agent_id）';

-- 运行执行 span（system/llm/tool/reply，parent_span_id 组树）
CREATE TABLE IF NOT EXISTS agent_run_spans (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    run_id VARCHAR(64) NOT NULL,
    span_id VARCHAR(64) NOT NULL,
    parent_span_id VARCHAR(64),
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(128),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_ms INTEGER,
    input JSONB,
    output JSONB,
    tokens INTEGER,
    status VARCHAR(16),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_run_spans_run
ON agent_run_spans (run_id);
COMMENT ON TABLE agent_run_spans IS
'Agent 运行执行 span（system/llm/tool/reply，parent_span_id 组树）';
COMMENT ON COLUMN agent_run_spans.kind IS
'span 类型: system, llm, tool, reply';
