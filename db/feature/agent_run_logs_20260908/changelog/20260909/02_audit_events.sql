-- [变更说明] 新增治理审计事件表 audit_events（SQLite audit.db 的 PG 替代；ts 为 UTC 毫秒时间戳）
-- [变更时间] 2026-09-09
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- ============================================================
-- audit_events：治理审计事件表
-- alembic 等价路径：0015_audit_events
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_events (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            BIGSERIAL PRIMARY KEY,
    ts            BIGINT NOT NULL,
    workspace_dir TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    target        TEXT NOT NULL,
    decision      VARCHAR(32) NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    extra         JSONB,
    actor_id      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_events_ts
    ON audit_events (tenant_id, ts);

CREATE INDEX IF NOT EXISTS idx_audit_events_workspace
    ON audit_events (tenant_id, workspace_dir);

CREATE INDEX IF NOT EXISTS idx_audit_events_agent
    ON audit_events (tenant_id, agent_id);

CREATE INDEX IF NOT EXISTS idx_audit_events_tool
    ON audit_events (tenant_id, tool_name);

COMMENT ON TABLE audit_events IS '治理审计事件表：每次 assert_policy/audit 调用的 5W 记录（SQLite audit.db 的 PG 替代；ts 为 UTC 毫秒时间戳）';

COMMENT ON COLUMN audit_events.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN audit_events.id IS '事件行 ID（BIGSERIAL 自增主键）';

COMMENT ON COLUMN audit_events.ts IS '事件时间（UTC 毫秒时间戳）';

COMMENT ON COLUMN audit_events.workspace_dir IS '事件所属工作区路径';

COMMENT ON COLUMN audit_events.agent_id IS '执行调用的智能体标识';

COMMENT ON COLUMN audit_events.session_id IS '调用所属会话标识';

COMMENT ON COLUMN audit_events.tool_name IS '被治理的工具名';

COMMENT ON COLUMN audit_events.target IS '工具调用目标';

COMMENT ON COLUMN audit_events.decision IS '治理决策: allow-允许, deny-拒绝, ask-询问, sandbox_fallback-沙箱降级';

COMMENT ON COLUMN audit_events.reason IS '决策原因说明';

COMMENT ON COLUMN audit_events.extra IS '扩展信息（JSONB）';

COMMENT ON COLUMN audit_events.actor_id IS '可信用户身份（M4；匿名调用为空串）';
