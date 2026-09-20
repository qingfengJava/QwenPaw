-- ============================================================
-- 变更说明: 知识本体平台 T6 —— 绑定主体泛化（数字员工与专家团接入）：
--           agent_kb_bindings 加 principal_type VARCHAR(16) NOT NULL
--           DEFAULT 'agent'（agent-数字员工直绑存量语义 / team-专家组
--           绑，team 行的 agent_id 列存 team_{team_id} 运行态形态，
--           列名不改保兼容）。纯加列不动唯一键，绑定解析在应用层。
-- 变更时间: 2026-09-20
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0048_binding_principal（Revises 0047_kb_ontology）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

ALTER TABLE agent_kb_bindings ADD COLUMN IF NOT EXISTS principal_type
    VARCHAR(16) NOT NULL DEFAULT 'agent';

COMMENT ON COLUMN agent_kb_bindings.principal_type IS
    '绑定主体类型: agent-数字员工直绑(存量语义), team-专家组绑'
    '(agent_id 列存 team_{team_id} 运行态形态, 列名不改保兼容)';

-- 验证：SELECT count(*) FROM information_schema.columns
--       WHERE table_name='agent_kb_bindings' AND column_name='principal_type';
