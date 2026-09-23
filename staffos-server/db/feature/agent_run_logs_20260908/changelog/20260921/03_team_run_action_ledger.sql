-- ============================================================
-- 变更说明: 专家团职责协作 T4 —— 动作账本：新表 team_run_actions，
--           业务外部动作**先落库后执行**（registered → executed/
--           failed/reverted），action_key 在 run 内唯一（幂等重放
--           复用原记录，防外部副作用重复发生）；envelope 列存放
--           服务端生成的 TrustedExecutionEnvelope 快照（控制面
--           授权边界留痕；外部请求自填无效）。
-- 变更时间: 2026-09-21
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0051_team_run_action_ledger（Revises 0050_team_run_contracts_ledger）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

CREATE TABLE IF NOT EXISTS team_run_actions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    run_id VARCHAR(64) NOT NULL,
    node_key VARCHAR(128) NOT NULL DEFAULT '',
    attempt_id VARCHAR(64) NOT NULL DEFAULT '',
    action_type VARCHAR(64) NOT NULL DEFAULT '',
    action_key VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'registered',
    envelope JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_team_run_actions PRIMARY KEY (tenant_id, id)
);

-- 幂等键唯一（活跃登记）：registered/executed/failed 占键防重复执行
-- 外部副作用；reverted（恢复/撤权）释放键，同一逻辑动作可重新登记
ALTER TABLE team_run_actions
    DROP CONSTRAINT IF EXISTS uq_team_run_actions_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_team_run_actions_key
    ON team_run_actions (tenant_id, run_id, action_key)
    WHERE status <> 'reverted';

CREATE INDEX IF NOT EXISTS ix_team_run_actions_run
    ON team_run_actions (tenant_id, run_id, status);

COMMENT ON TABLE team_run_actions IS
    '业务动作账本(T4): 外部动作先落库后执行, action_key run 内幂等, '
    'envelope 为服务端可信载荷快照';

COMMENT ON COLUMN team_run_actions.status IS
    '状态: registered-已登记未执行, executed-已执行, '
    'failed-执行失败, reverted-已回滚/作废';

-- 验证：SELECT count(*) FROM information_schema.tables
--       WHERE table_name = 'team_run_actions';
