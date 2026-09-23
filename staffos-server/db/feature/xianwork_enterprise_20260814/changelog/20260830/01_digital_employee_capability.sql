-- ============================================================
-- 变更说明: 数字员工能力层（StaffDeck 能力移植）——
--           1) experts 扩 4 列档案字段：department（部门）/
--              work_styles（工作风格 JSONB 数组）/ work_modes
--              （工作方式 JSONB 数组）/ hire_date（入职时间）。
--              在线状态为派生值（已发布=在线），不落列
--           2) 新表 expert_resource_bindings：员工能力挂载枢纽
--              （sop/knowledge_base/tool 三类；技能绑定沿用
--              expert_skills 不迁移——它是发布物化链的权威）
--           3) 新表 sops + sop_versions：SOP 流程资产 + 版本链。
--              SOP 只作资产注入 workforce 规划/验收，不替代引擎
--              （见 docs/design/2026-08-30-digital-employee-capability-layer.md 决策 D3）
--           4) 新表 expert_memories：员工分桶记忆
--              （kind=profile|preference|fact，dedup_key 语义幂等）
--           5) 新表 expert_scheduled_tasks + expert_task_runs：
--              员工定时任务投影台账 + 执行留痕（调度权威在
--              CronManager，job_id 前缀 expert_task_，复用
--              automations「投影+权威分离」成熟模式）
--           6) 新表 message_feedback：消息级好评/差评采集
--              （(message_id,user_id) 唯一，重复提交=覆盖）
--           7) 新表 evolution_proposals：演进提案生命周期
--              （draft→ready_for_review→approved|rejected→
--              published|rolled_back）
-- 变更时间: 2026-08-30
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0012_digital_employee_capability（Revises 0011_builtin_sample_tasks）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. experts 扩档案列（全部有默认值，存量行语义不变）
-- ------------------------------------------------------------

ALTER TABLE experts ADD COLUMN IF NOT EXISTS department TEXT NOT NULL DEFAULT '';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_styles JSONB NOT NULL DEFAULT '[]';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_modes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS hire_date TIMESTAMPTZ;

COMMENT ON COLUMN experts.department IS '部门（员工档案展示与统计维度；组织树关联为后续版本预留，本列存部门名）';
COMMENT ON COLUMN experts.work_styles IS '工作风格数组（JSONB 字符串数组，如 ["耐心细致","结果导向"]，档案卡标签行）';
COMMENT ON COLUMN experts.work_modes IS '工作方式数组（JSONB 字符串数组，如 ["7x24 值守","定时巡检"]，档案卡标签行）';
COMMENT ON COLUMN experts.hire_date IS '入职时间（员工档案展示；NULL=未填，创建时默认 now())';

-- ------------------------------------------------------------
-- 2. expert_resource_bindings：能力挂载枢纽（sop/knowledge_base/tool）
--    技能绑定权威仍是 expert_skills（发布物化链依赖），勿合并
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS expert_resource_bindings (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    expert_id     VARCHAR(64) NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id   TEXT NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    seq           INTEGER NOT NULL DEFAULT 0,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_resource_bindings PRIMARY KEY (tenant_id, expert_id, resource_type, resource_id),
    CONSTRAINT ck_expert_resource_bindings_type CHECK (resource_type IN ('sop', 'knowledge_base', 'tool'))
);

COMMENT ON TABLE expert_resource_bindings IS '员工能力挂载：数字员工 × 流程资产/知识库/工具 的绑定关系（enabled 停用不丢绑定；metadata 存挂载时名称快照防悬挂）';
COMMENT ON COLUMN expert_resource_bindings.resource_type IS '资源类型: sop-SOP 流程资产(sops.id) / knowledge_base-知识库(kb 文档 id) / tool-工具名';
COMMENT ON COLUMN expert_resource_bindings.metadata IS '挂载元数据 JSONB（name 快照等；资源本体删除后列表仍可显示快照名）';

CREATE INDEX IF NOT EXISTS idx_expert_resource_bindings_expert
    ON expert_resource_bindings (tenant_id, expert_id, resource_type);

-- ------------------------------------------------------------
-- 3. sops + sop_versions：SOP 流程资产 + 版本链
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sops (
    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
    id              VARCHAR(64) NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    business_domain TEXT NOT NULL DEFAULT '',
    goal            TEXT NOT NULL DEFAULT '',
    nodes           JSONB NOT NULL DEFAULT '[]',
    edges           JSONB NOT NULL DEFAULT '[]',
    slots           JSONB NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'draft',
    version         INTEGER NOT NULL DEFAULT 1,
    owner_id        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sops PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_sops_status CHECK (status IN ('draft', 'published', 'archived'))
);

COMMENT ON TABLE sops IS 'SOP 流程资产：结构化经验流程（节点链+槽位+验收要点），绑定到员工后注入 workforce 规划参考与验收 rubric，不作为硬状态机执行';
COMMENT ON COLUMN sops.goal IS '流程总目标（一句话，注入规划上下文的锚点）';
COMMENT ON COLUMN sops.nodes IS '节点数组 [{id,title,instruction,expected_outcome,tools[]}]：expected_outcome 供 Verifier rubric 引用';
COMMENT ON COLUMN sops.edges IS '边数组 [{from,to,condition}]：condition 为自然语言转移条件（规划参考，不做硬路由）';
COMMENT ON COLUMN sops.slots IS '槽位数组 [{key,label,required,ask_prompt}]：执行期缺失时可澄清补齐';
COMMENT ON COLUMN sops.status IS '状态: draft-草稿 / published-已发布(可绑定生效) / archived-归档';
COMMENT ON COLUMN sops.version IS '当前版本号（发布时 +1 并写 sop_versions 快照）';

CREATE TABLE IF NOT EXISTS sop_versions (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    sop_id       VARCHAR(64) NOT NULL,
    version      INTEGER NOT NULL,
    snapshot     JSONB NOT NULL,
    change_note  TEXT NOT NULL DEFAULT '',
    published_by TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sop_versions PRIMARY KEY (tenant_id, sop_id, version)
);

COMMENT ON TABLE sop_versions IS 'SOP 发布版本快照（不可变；rollback=取历史快照发布为新版本）';
COMMENT ON COLUMN sop_versions.snapshot IS '发布时 SOP 全量字段快照 JSONB（nodes/edges/slots/goal 等）';

CREATE INDEX IF NOT EXISTS idx_sops_owner ON sops (tenant_id, owner_id);

-- ------------------------------------------------------------
-- 4. expert_memories：员工分桶记忆
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS expert_memories (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    id         VARCHAR(64) NOT NULL,
    expert_id  VARCHAR(64) NOT NULL,
    user_id    TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    content    TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    dedup_key  TEXT NOT NULL DEFAULT '',
    metadata   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_memories PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_expert_memories_kind CHECK (kind IN ('profile', 'preference', 'fact'))
);

COMMENT ON TABLE expert_memories IS '员工分桶长期记忆：数字员工对某用户（user_id 空=组织级公共）的结构化认知，UI 可视化管理；发布物化进专家 workspace memory/ 供上下文加载';
COMMENT ON COLUMN expert_memories.kind IS '记忆分桶: profile-用户画像 / preference-偏好 / fact-事实';
COMMENT ON COLUMN expert_memories.importance IS '重要度 0~1（物化时按重要度+时间排序截断）';
COMMENT ON COLUMN expert_memories.dedup_key IS '语义去重键（同 expert+user+kind 内唯一，upsert 锚点；空串=不去重）';

CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_memories_dedup
    ON expert_memories (tenant_id, expert_id, user_id, kind, dedup_key)
    WHERE dedup_key <> '';
CREATE INDEX IF NOT EXISTS idx_expert_memories_scope
    ON expert_memories (tenant_id, expert_id, user_id, kind);

-- ------------------------------------------------------------
-- 5. expert_scheduled_tasks + expert_task_runs：员工定时任务
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS expert_scheduled_tasks (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            VARCHAR(64) NOT NULL,
    expert_id     VARCHAR(64) NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    task_prompt   TEXT NOT NULL,
    schedule_type TEXT NOT NULL DEFAULT 'cron',
    schedule_json JSONB NOT NULL DEFAULT '{}',
    timezone      TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status        TEXT NOT NULL DEFAULT 'active',
    cron_job_id   TEXT NOT NULL DEFAULT '',
    next_run_at   TIMESTAMPTZ,
    last_run_at   TIMESTAMPTZ,
    last_status   TEXT NOT NULL DEFAULT '',
    run_count     BIGINT NOT NULL DEFAULT 0,
    owner_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_scheduled_tasks PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_expert_scheduled_tasks_type CHECK (schedule_type IN ('cron', 'once')),
    CONSTRAINT ck_expert_scheduled_tasks_status CHECK (status IN ('active', 'paused', 'completed', 'archived'))
);

COMMENT ON TABLE expert_scheduled_tasks IS '员工定时任务投影台账（调度权威在 CronManager，job_id=cron_job_id；执行=对该专家发起一次真实任务，结果写 expert_task_runs 并进工作记录）';
COMMENT ON COLUMN expert_scheduled_tasks.task_prompt IS '执行指令（触发时作为任务目标投给该数字员工，走 workforce 引擎执行）';
COMMENT ON COLUMN expert_scheduled_tasks.schedule_type IS '调度类型: cron-周期(crontab 5 段) / once-一次性(run_at)';
COMMENT ON COLUMN expert_scheduled_tasks.schedule_json IS '调度参数 JSONB：cron 形如 {"cron":"0 9 * * 1-5"}；once 形如 {"run_at":"2026-09-01T09:00:00+08:00"}';
COMMENT ON COLUMN expert_scheduled_tasks.timezone IS 'IANA 时区（调度基准，默认 Asia/Shanghai）';
COMMENT ON COLUMN expert_scheduled_tasks.status IS '状态: active-启用 / paused-暂停 / completed-一次性已完成 / archived-归档(删除语义)';
COMMENT ON COLUMN expert_scheduled_tasks.cron_job_id IS 'CronManager 权威 job id（expert_task_<id>；空=尚未注册）';
COMMENT ON COLUMN expert_scheduled_tasks.last_status IS '最近一次执行结果: succeeded/failed/running/空';

CREATE TABLE IF NOT EXISTS expert_task_runs (
    tenant_id     VARCHAR(64) NOT NULL DEFAULT 'default',
    id            VARCHAR(64) NOT NULL,
    task_id       VARCHAR(64) NOT NULL,
    expert_id     VARCHAR(64) NOT NULL,
    scheduled_for TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running',
    result_summary TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    CONSTRAINT pk_expert_task_runs PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_expert_task_runs_status CHECK (status IN ('running', 'succeeded', 'failed'))
);

COMMENT ON TABLE expert_task_runs IS '定时任务执行留痕：每次触发一行（scheduled_for 为幂等锚，同任务同触发点唯一）';
COMMENT ON COLUMN expert_task_runs.scheduled_for IS '计划触发时间点（幂等锚：唯一索引防同点重复执行；NULL=手动 run-now）';

CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_task_runs_idem
    ON expert_task_runs (tenant_id, task_id, scheduled_for)
    WHERE scheduled_for IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_expert_task_runs_task
    ON expert_task_runs (tenant_id, task_id, started_at DESC);

-- ------------------------------------------------------------
-- 6. message_feedback：消息级反馈
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS message_feedback (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    id          VARCHAR(64) NOT NULL,
    message_id  TEXT NOT NULL,
    session_id  TEXT NOT NULL DEFAULT '',
    expert_id   TEXT NOT NULL DEFAULT '',
    user_id     TEXT NOT NULL DEFAULT '',
    rating      TEXT NOT NULL,
    comment     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_message_feedback PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_message_feedback_rating CHECK (rating IN ('up', 'down'))
);

COMMENT ON TABLE message_feedback IS '消息级好评/差评采集（(message_id,user_id) 唯一；重复提交=覆盖语义，支撑反馈驱动演进）';
COMMENT ON COLUMN message_feedback.expert_id IS '归属数字员工（会话由专家承载时回填；空=非专家会话反馈）';
COMMENT ON COLUMN message_feedback.rating IS '评分: up-好评 / down-差评';

CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_once
    ON message_feedback (tenant_id, message_id, user_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_expert
    ON message_feedback (tenant_id, expert_id, created_at DESC);

-- ------------------------------------------------------------
-- 7. evolution_proposals：演进提案
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evolution_proposals (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    id           VARCHAR(64) NOT NULL,
    expert_id    VARCHAR(64) NOT NULL,
    title        TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'feedback',
    risk_level   TEXT NOT NULL DEFAULT 'low',
    hypothesis   TEXT NOT NULL DEFAULT '',
    evidence     JSONB NOT NULL DEFAULT '[]',
    candidate    JSONB NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'draft',
    reviewed_by  TEXT,
    reviewed_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_evolution_proposals PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_evolution_proposals_trigger CHECK (trigger_type IN ('feedback', 'manual', 'audit')),
    CONSTRAINT ck_evolution_proposals_risk CHECK (risk_level IN ('low', 'medium', 'high')),
    CONSTRAINT ck_evolution_proposals_status CHECK (status IN ('draft', 'ready_for_review', 'approved', 'rejected', 'published', 'rolled_back'))
);

COMMENT ON TABLE evolution_proposals IS '演进提案：反馈/审计驱动的员工能力变更建议（SOP/人设/技能），人工审批后发布，留痕可回滚（StaffDeck 成长记录对应物）';
COMMENT ON COLUMN evolution_proposals.trigger_type IS '触发来源: feedback-用户反馈 / manual-人工创建 / audit-审计巡检';
COMMENT ON COLUMN evolution_proposals.risk_level IS '风险等级: low/medium/high（high 需管理员审批）';
COMMENT ON COLUMN evolution_proposals.hypothesis IS '改进假设（为什么这个变更能解决问题）';
COMMENT ON COLUMN evolution_proposals.evidence IS '证据数组（反馈 id/消息摘录/统计数据）';
COMMENT ON COLUMN evolution_proposals.candidate IS '变更体 JSONB（target=sop|system_prompt|skills + 变更内容/diff）';
COMMENT ON COLUMN evolution_proposals.status IS '状态: draft-起草 / ready_for_review-待审 / approved-已批准 / rejected-已驳回 / published-已发布 / rolled_back-已回滚';

CREATE INDEX IF NOT EXISTS idx_evolution_proposals_expert
    ON evolution_proposals (tenant_id, expert_id, status, updated_at DESC);

-- ------------------------------------------------------------
-- 8. Alembic 版本标记推进（0011 → 0012）
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0012_digital_employee_capability';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0012_digital_employee_capability');
    END IF;
END $$;

COMMIT;
