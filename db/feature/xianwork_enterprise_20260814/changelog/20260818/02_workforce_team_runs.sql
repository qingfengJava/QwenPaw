-- ============================================================
-- 变更说明: Workforce 团队任务运行时 —— 新增 team_runs /
--           team_run_nodes 两表，承载专家团任务的 DAG 编排、
--           逐节点契约/结果/验收/返工留痕、版本化上下文束与
--           熔断计数（两级 Harness：中央大脑 + 子员工）。
--           1) team_runs：一次专家团任务的运行实例（状态机：
--              planning/awaiting_confirm/running/verifying/
--              repairing/aggregating/done/failed/escalated/
--              canceled/interrupted；plan/policy/context_bundle
--              全 JSONB，与 agent_spec 快照模式一致）
--           2) team_run_nodes：DAG 节点执行与验收留痕（复合主键
--              tenant_id+run_id+node_key；contract/result/repair
--              三大契约 JSONB；attempt 支持返工轮次与断点续跑；
--              assignee_user_id 为跨用户数字员工移交预留）
--           3) 不动既有 tasks 看板表（人工任务语义隔离）；
--              feed_events 仅扩 kind 字符串，无 DDL 变更
-- 变更时间: 2026-08-18
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0010_workforce_team_runs（Revises 0009_expert_catalog）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. team_runs：专家团任务运行实例表
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS team_runs (
    tenant_id         VARCHAR(64) NOT NULL DEFAULT 'default',
    id                VARCHAR(64) NOT NULL,
    team_id           VARCHAR(64) NOT NULL,
    project_id        VARCHAR(64),
    source_chat_id    VARCHAR(128),
    initiator_id      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'planning',
    goal              TEXT NOT NULL DEFAULT '',
    plan              JSONB NOT NULL DEFAULT '{}',
    policy            JSONB NOT NULL DEFAULT '{}',
    context_bundle    JSONB NOT NULL DEFAULT '{}',
    context_version   INTEGER NOT NULL DEFAULT 1,
    summary           TEXT NOT NULL DEFAULT '',
    result            JSONB NOT NULL DEFAULT '{}',
    clarification     JSONB NOT NULL DEFAULT '{}',
    repair_count      INTEGER NOT NULL DEFAULT 0,
    replan_count      INTEGER NOT NULL DEFAULT 0,
    error             TEXT NOT NULL DEFAULT '',
    escalation_reason TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_team_runs PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE team_runs IS 'Workforce 团队任务运行实例（两级 Harness：中央大脑 Plan-then-Execute 编排已发布专家团成员；状态机含熔断升级人工与断点续跑）';
COMMENT ON COLUMN team_runs.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN team_runs.id IS '运行实例 ID（应用层生成，如 run_xxx）';
COMMENT ON COLUMN team_runs.team_id IS '专家团 ID（弱引用 expert_teams.id；团队删除后历史 run 保留）';
COMMENT ON COLUMN team_runs.project_id IS '关联项目 ID（可空；跨用户移交要求本列非空以校验 project_members 归属）';
COMMENT ON COLUMN team_runs.source_chat_id IS '来源会话 ID（可空；聊天升级入口创建时记录，完成后汇总卡片回推该会话）';
COMMENT ON COLUMN team_runs.initiator_id IS '发起用户（权限主体；列表与详情按此过滤）';
COMMENT ON COLUMN team_runs.status IS '状态: planning-规划中, awaiting_confirm-等待用户澄清, running-执行中, verifying-验收中, repairing-返工中, aggregating-汇总中, done-完成, failed-失败, escalated-熔断升级人工, canceled-已取消, interrupted-进程中断可续跑';
COMMENT ON COLUMN team_runs.goal IS '用户原始需求（goal 文本，规划输入）';
COMMENT ON COLUMN team_runs.plan IS '任务图 DagPlan（nodes+deps+assignee；JSONB 快照，规划一次成型）';
COMMENT ON COLUMN team_runs.policy IS '熔断策略 RunPolicy（max_repair_per_node/max_replan/max_total_seconds/max_total_tokens/parallelism；纯计数器）';
COMMENT ON COLUMN team_runs.context_bundle IS '版本化上下文束 ContextBundle（global_ctx/task_ctx/execution_ctx；节点间与跨用户传递的唯一介质，禁止聊天记录透传）';
COMMENT ON COLUMN team_runs.context_version IS '上下文版本号（单调递增；全局决策变更/澄清答复/移交时 +1，后续节点契约引用新版本）';
COMMENT ON COLUMN team_runs.summary IS '最终汇总文本（中央大脑 final 节点产出，回推聊天卡片用）';
COMMENT ON COLUMN team_runs.result IS '最终结构化结果（final 节点 ResultContract 的 result 部分）';
COMMENT ON COLUMN team_runs.clarification IS '澄清问答记录 Clarification（questions/options/answers；awaiting_confirm 状态的输入输出）';
COMMENT ON COLUMN team_runs.repair_count IS '累计返工次数（全节点求和；观测指标）';
COMMENT ON COLUMN team_runs.replan_count IS '累计重规划次数（熔断计数）';
COMMENT ON COLUMN team_runs.error IS '失败原因（failed 终态时填写）';
COMMENT ON COLUMN team_runs.escalation_reason IS '熔断原因（escalated 终态时填写：max_repair/max_replan/max_tokens/max_time）';
COMMENT ON COLUMN team_runs.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN team_runs.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 2. team_run_nodes：DAG 节点执行与验收留痕表
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS team_run_nodes (
    tenant_id         VARCHAR(64) NOT NULL DEFAULT 'default',
    run_id            VARCHAR(64) NOT NULL,
    node_key          VARCHAR(128) NOT NULL,
    assignee_expert_id VARCHAR(64) NOT NULL DEFAULT '',
    assignee_user_id  TEXT,
    node_type         TEXT NOT NULL DEFAULT 'task',
    status            TEXT NOT NULL DEFAULT 'pending',
    contract          JSONB NOT NULL DEFAULT '{}',
    result            JSONB NOT NULL DEFAULT '{}',
    repair            JSONB NOT NULL DEFAULT '{}',
    verdict           TEXT NOT NULL DEFAULT '',
    repair_count      INTEGER NOT NULL DEFAULT 0,
    session_id        TEXT NOT NULL DEFAULT '',
    token_cost        BIGINT NOT NULL DEFAULT 0,
    attempt           INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_team_run_nodes PRIMARY KEY (tenant_id, run_id, node_key)
);

COMMENT ON TABLE team_run_nodes IS 'Workforce DAG 节点执行留痕（每节点：TaskContract 委派 → ResultContract 回传 → 中央验收 verdict → RepairContract 返工；attempt 支持断点续跑）';
COMMENT ON COLUMN team_run_nodes.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN team_run_nodes.run_id IS '运行实例 ID（弱引用 team_runs.id；run 删除时级联清理由应用层负责）';
COMMENT ON COLUMN team_run_nodes.node_key IS '节点标识（run 内唯一；DagPlan.nodes[].node_key）';
COMMENT ON COLUMN team_run_nodes.assignee_expert_id IS '指派专家 ID（experts.id；final/integration 节点为空=中央大脑自执行）';
COMMENT ON COLUMN team_run_nodes.assignee_user_id IS '跨用户移交预留：指派给目标用户的专家（NULL=团队内成员；移交要求 run.project_id 非空且目标用户为 project_members 成员）';
COMMENT ON COLUMN team_run_nodes.node_type IS '节点类型: task-普通任务, repair-返工, integration-集成聚合, final-最终汇总, clarify-澄清';
COMMENT ON COLUMN team_run_nodes.status IS '节点状态: pending-待执行, delegated-已委派, running-执行中, verifying-验收中, repairing-返工中, done-完成, failed-失败';
COMMENT ON COLUMN team_run_nodes.contract IS '任务契约 TaskContract（objective/global_context 快照/parent_decision/expected_output/quality_criteria 等）';
COMMENT ON COLUMN team_run_nodes.result IS '结果契约 ResultContract（status/result/evidence/decisions/assumptions/confidence/needs_review）';
COMMENT ON COLUMN team_run_nodes.repair IS '返工契约 RepairContract（issues/expected_change/preserve/acceptance；最近一次返工指令）';
COMMENT ON COLUMN team_run_nodes.verdict IS '最近一次验收裁决: PASS-通过, FAIL-返工, ESCALATE-升级人工（空=未验收）';
COMMENT ON COLUMN team_run_nodes.repair_count IS '本节点返工次数（超 RunPolicy.max_repair_per_node 即熔断）';
COMMENT ON COLUMN team_run_nodes.session_id IS '成员专家的独立会话 ID（每节点独立 session，跨会话天然并发；返工轮复用以延续成员上下文）';
COMMENT ON COLUMN team_run_nodes.token_cost IS '本节点累计 token 消耗（委派回执 usage 聚合）';
COMMENT ON COLUMN team_run_nodes.attempt IS '执行轮次（0=未执行；每委派一次 +1，含返工轮；断点续跑时从最新 attempt 恢复）';
COMMENT ON COLUMN team_run_nodes.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN team_run_nodes.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 3. 查询索引
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_team_runs_team
    ON team_runs (tenant_id, team_id);

CREATE INDEX IF NOT EXISTS ix_team_runs_status
    ON team_runs (tenant_id, status);

CREATE INDEX IF NOT EXISTS ix_team_runs_project
    ON team_runs (tenant_id, project_id);

CREATE INDEX IF NOT EXISTS ix_team_run_nodes_run
    ON team_run_nodes (tenant_id, run_id);

-- ------------------------------------------------------------
-- 4. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0010_workforce_team_runs';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0010_workforce_team_runs');
    END IF;
END $$;

COMMIT;
