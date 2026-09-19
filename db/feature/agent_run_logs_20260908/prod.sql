-- [变更说明] 统一补齐缺失的表级/列级备注（14 张表 + 166 列，COMMENT ON 幂等可重复执行）
-- [变更时间] 2026-09-08
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- ============================================================
-- 一、表级备注（14 张缺失表）
-- ============================================================

COMMENT ON TABLE alembic_version IS '数据库迁移版本表（Alembic 框架内部表，记录当前 schema 所处版本号）';

COMMENT ON TABLE evolution_proposals IS '专家演进提案表（反馈驱动的专家变更提案与人工审核生命周期，0012 数字员工能力层）';

COMMENT ON TABLE expert_api_keys IS '专家开放 API 密钥表（P4 /api/open 凭据面，明文仅签发时返回一次，持久层只存 SHA-256 哈希与展示前缀）';

COMMENT ON TABLE expert_memories IS '专家长期记忆表（按 profile/preference/fact 分桶，dedup_key 幂等去重）';

COMMENT ON TABLE expert_resource_bindings IS '专家资源绑定表（能力挂载 hub：sop/knowledge_base/tool 三类，技能仍以 expert_skills 为发布链权威）';

COMMENT ON TABLE expert_scheduled_tasks IS '专家定时任务表（调度权威在 CronManager，本表为任务面投影，job id 前缀 expert_task_）';

COMMENT ON TABLE expert_task_runs IS '专家定时任务执行记录表（每次执行留痕，(tenant_id, task_id, scheduled_for) 唯一索引保证同一调度时刻幂等）';

COMMENT ON TABLE media_files IS '聊天媒体文件表（console 上传与 Agent 产出的持久字节副本，0007 升级为会话文件登记表，本地 media/ 为工作副本本表为数据库副本）';

COMMENT ON TABLE message_feedback IS '消息反馈表（消息粒度 👍/👎 收集，每用户每消息仅一条）';

COMMENT ON TABLE sop_versions IS 'SOP 版本快照表（发布时全量 JSONB 快照加变更说明，只增不改，与 sops 组成版本化流程资产）';

COMMENT ON TABLE sops IS 'SOP 流程资产表（版本化流程定义：节点/边/槽位 JSONB，注入 workforce 编排与校验，非硬状态机）';

COMMENT ON TABLE team_run_nodes IS '团队运行节点台账表（team_runs 的 DAG 节点级执行留痕：Task/Result/Repair 契约 JSONB 加 verdict，attempt 兼作崩溃恢复游标）';

COMMENT ON TABLE team_runs IS '团队运行表（workforce 两级 Harness 一次团队任务执行实例，planning 到 done/failed/escalated 状态机，plan/policy/context_bundle 为 JSONB 契约快照）';

COMMENT ON TABLE xian_workspaces IS 'XianWork 工作区登记表（用户认领的磁盘目录与名称映射，会话绑定复用 chats.meta.runtime_context.project_dir 机制，本表不存会话外键）';

-- ============================================================
-- 二、列级备注（166 个缺失列）
-- ============================================================

-- ---- alembic_version ----

COMMENT ON COLUMN alembic_version.version_num IS '当前 schema 版本号（Alembic 迁移链 head 标识）';

-- ---- evolution_proposals ----

COMMENT ON COLUMN evolution_proposals.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN evolution_proposals.id IS '提案 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN evolution_proposals.expert_id IS '目标专家 ID（experts.id）';

COMMENT ON COLUMN evolution_proposals.title IS '提案标题';

COMMENT ON COLUMN evolution_proposals.trigger_type IS '触发来源：feedback（用户反馈）/ manual（人工）/ audit（审计）';

COMMENT ON COLUMN evolution_proposals.risk_level IS '风险等级：low / medium / high';

COMMENT ON COLUMN evolution_proposals.hypothesis IS '变更假设（提案动机与预期收益描述）';

COMMENT ON COLUMN evolution_proposals.evidence IS '证据列表（JSONB 数组，支撑提案的反馈与审计摘录）';

COMMENT ON COLUMN evolution_proposals.candidate IS '变更候选内容（JSONB，拟应用的专家配置差异）';

COMMENT ON COLUMN evolution_proposals.status IS '审核状态：draft / ready_for_review / approved / rejected / published / rolled_back';

COMMENT ON COLUMN evolution_proposals.reviewed_by IS '审核人（用户名，可为 NULL 表示未审核）';

COMMENT ON COLUMN evolution_proposals.reviewed_at IS '审核时间（可为 NULL 表示未审核）';

COMMENT ON COLUMN evolution_proposals.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN evolution_proposals.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- expert_api_keys ----

COMMENT ON COLUMN expert_api_keys.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN expert_api_keys.id IS '密钥 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN expert_api_keys.expert_id IS '绑定专家 ID（权限边界：密钥仅能操作该专家）';

COMMENT ON COLUMN expert_api_keys.name IS '密钥名称（便于识别的展示名）';

COMMENT ON COLUMN expert_api_keys.key_hash IS '密钥 SHA-256 哈希（明文仅签发时返回一次，持久层只存哈希）';

COMMENT ON COLUMN expert_api_keys.key_prefix IS '密钥展示前缀（用于列表识别，不含完整密钥）';

COMMENT ON COLUMN expert_api_keys.created_by IS '签发人（用户名，可为 NULL）';

COMMENT ON COLUMN expert_api_keys.expires_at IS '过期时间（可为 NULL 表示永不过期）';

COMMENT ON COLUMN expert_api_keys.revoked_at IS '撤销时间（软撤销标记，非 NULL 即已吊销）';

COMMENT ON COLUMN expert_api_keys.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN expert_api_keys.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- expert_memories ----

COMMENT ON COLUMN expert_memories.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN expert_memories.id IS '记忆 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN expert_memories.expert_id IS '所属专家 ID（experts.id）';

COMMENT ON COLUMN expert_memories.user_id IS '记忆归属用户（空串表示专家全局记忆）';

COMMENT ON COLUMN expert_memories.kind IS '记忆类型：profile（画像）/ preference（偏好）/ fact（事实）';

COMMENT ON COLUMN expert_memories.content IS '记忆内容文本';

COMMENT ON COLUMN expert_memories.importance IS '重要度（0.0~1.0，默认 0.5，驱动检索排序）';

COMMENT ON COLUMN expert_memories.dedup_key IS '幂等去重键（非空时与 tenant/expert/user/kind 组合唯一）';

COMMENT ON COLUMN expert_memories.metadata IS '扩展元数据（JSONB）';

COMMENT ON COLUMN expert_memories.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN expert_memories.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- expert_resource_bindings ----

COMMENT ON COLUMN expert_resource_bindings.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN expert_resource_bindings.expert_id IS '专家 ID（experts.id）';

COMMENT ON COLUMN expert_resource_bindings.resource_type IS '资源类型：sop / knowledge_base / tool';

COMMENT ON COLUMN expert_resource_bindings.resource_id IS '资源 ID（对应各资源注册表主键）';

COMMENT ON COLUMN expert_resource_bindings.enabled IS '是否启用（挂载后可临时下线）';

COMMENT ON COLUMN expert_resource_bindings.seq IS '排序序号（同专家同类型内的展示与注入顺序）';

COMMENT ON COLUMN expert_resource_bindings.metadata IS '扩展元数据（JSONB）';

COMMENT ON COLUMN expert_resource_bindings.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN expert_resource_bindings.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- expert_scheduled_tasks ----

COMMENT ON COLUMN expert_scheduled_tasks.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN expert_scheduled_tasks.id IS '任务 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN expert_scheduled_tasks.expert_id IS '执行专家 ID（experts.id）';

COMMENT ON COLUMN expert_scheduled_tasks.name IS '任务名称';

COMMENT ON COLUMN expert_scheduled_tasks.description IS '任务描述';

COMMENT ON COLUMN expert_scheduled_tasks.task_prompt IS '任务提示词（每次触发下发给专家的 prompt）';

COMMENT ON COLUMN expert_scheduled_tasks.schedule_type IS '调度类型：cron（周期）/ once（单次）';

COMMENT ON COLUMN expert_scheduled_tasks.schedule_json IS '调度参数（JSONB：cron 表达式或 once 触发时间）';

COMMENT ON COLUMN expert_scheduled_tasks.timezone IS '时区（默认 Asia/Shanghai）';

COMMENT ON COLUMN expert_scheduled_tasks.status IS '任务状态：active / paused / completed / archived';

COMMENT ON COLUMN expert_scheduled_tasks.cron_job_id IS 'CronManager 任务句柄（job id 前缀 expert_task_，空串表示未注册）';

COMMENT ON COLUMN expert_scheduled_tasks.next_run_at IS '下次触发时间';

COMMENT ON COLUMN expert_scheduled_tasks.last_run_at IS '最近触发时间';

COMMENT ON COLUMN expert_scheduled_tasks.last_status IS '最近一次执行结果摘要';

COMMENT ON COLUMN expert_scheduled_tasks.run_count IS '累计执行次数';

COMMENT ON COLUMN expert_scheduled_tasks.owner_id IS '归属账号（创建者用户名）';

COMMENT ON COLUMN expert_scheduled_tasks.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN expert_scheduled_tasks.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- expert_task_runs ----

COMMENT ON COLUMN expert_task_runs.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN expert_task_runs.id IS '执行记录 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN expert_task_runs.task_id IS '所属定时任务 ID（expert_scheduled_tasks.id）';

COMMENT ON COLUMN expert_task_runs.expert_id IS '执行专家 ID（experts.id）';

COMMENT ON COLUMN expert_task_runs.scheduled_for IS '计划触发时间（与 tenant/task 组合唯一，幂等锚点）';

COMMENT ON COLUMN expert_task_runs.status IS '执行状态：running / succeeded / failed';

COMMENT ON COLUMN expert_task_runs.result_summary IS '执行结果摘要';

COMMENT ON COLUMN expert_task_runs.error IS '失败原因（成功为空串）';

COMMENT ON COLUMN expert_task_runs.started_at IS '开始时间（DB 默认 now）';

COMMENT ON COLUMN expert_task_runs.finished_at IS '结束时间（可为 NULL 表示进行中）';

-- ---- expert_teams（补齐存量缺漏 2 列）----

COMMENT ON COLUMN expert_teams.sample_tasks IS '任务示例模板（JSONB [{title,prompt}]，详情页点击即以 prompt 为 goal 创建团队 run 的运营位）';

COMMENT ON COLUMN expert_teams.showcase IS '使用案例（JSONB [{title,desc,tags}] 静态运营位，与 team_runs 真实交付投影并存）';

-- ---- experts（补齐存量缺漏 6 列）----

COMMENT ON COLUMN experts.sample_tasks IS '任务示例模板（JSONB [{title,prompt}]，详情页点击即以 prompt 创建运行的运营位）';

COMMENT ON COLUMN experts.showcase IS '使用案例（JSONB [{title,desc,tags}] 静态运营位）';

COMMENT ON COLUMN experts.department IS '所属部门（0012 数字员工档案列，对应 departments 域）';

COMMENT ON COLUMN experts.work_styles IS '工作风格标签（JSONB 字符串数组）';

COMMENT ON COLUMN experts.work_modes IS '工作模式标签（JSONB 字符串数组）';

COMMENT ON COLUMN experts.hire_date IS '入职时间（数字员工档案，可为 NULL）';

-- ---- media_files（补齐存量缺漏 8 列）----

COMMENT ON COLUMN media_files.stored_name IS '存储文件名（PG 与本地双写一致的对象键）';

COMMENT ON COLUMN media_files.file_name IS '原始文件名（用户上传时的显示名）';

COMMENT ON COLUMN media_files.media_type IS 'MIME 类型（默认 application/octet-stream）';

COMMENT ON COLUMN media_files.size IS '文件字节数';

COMMENT ON COLUMN media_files.data IS '文件字节内容（bytea，storage_type=db 时可从库内恢复）';

COMMENT ON COLUMN media_files.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN media_files.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN media_files.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- message_feedback ----

COMMENT ON COLUMN message_feedback.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN message_feedback.id IS '反馈记录 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN message_feedback.message_id IS '被评价的消息 ID';

COMMENT ON COLUMN message_feedback.session_id IS '所属会话 ID（冗余关联，便于按会话聚合）';

COMMENT ON COLUMN message_feedback.expert_id IS '所属专家 ID（冗余关联，便于按专家聚合）';

COMMENT ON COLUMN message_feedback.user_id IS '评价用户（与 message_id 组合唯一：一人一消息一条）';

COMMENT ON COLUMN message_feedback.rating IS '评价方向：up / down';

COMMENT ON COLUMN message_feedback.comment IS '评价附言（可选文字反馈）';

COMMENT ON COLUMN message_feedback.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN message_feedback.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- sop_versions ----

COMMENT ON COLUMN sop_versions.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN sop_versions.sop_id IS '所属 SOP ID（sops.id）';

COMMENT ON COLUMN sop_versions.version IS '版本号（每次发布自增）';

COMMENT ON COLUMN sop_versions.snapshot IS '版本全量快照（JSONB：发布时刻的 SOP 完整定义）';

COMMENT ON COLUMN sop_versions.change_note IS '变更说明（发布时填写）';

COMMENT ON COLUMN sop_versions.published_by IS '发布人（用户名，可为 NULL）';

COMMENT ON COLUMN sop_versions.created_at IS '快照创建时间（DB 自动维护，UTC）';

-- ---- sops ----

COMMENT ON COLUMN sops.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN sops.id IS 'SOP ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN sops.name IS 'SOP 名称';

COMMENT ON COLUMN sops.description IS 'SOP 描述';

COMMENT ON COLUMN sops.business_domain IS '业务域标签（流程归类）';

COMMENT ON COLUMN sops.goal IS '流程目标（注入 workforce 时给中央大脑的目标描述）';

COMMENT ON COLUMN sops.nodes IS '流程节点（JSONB 数组）';

COMMENT ON COLUMN sops.edges IS '流程连线（JSONB 数组）';

COMMENT ON COLUMN sops.slots IS '流程槽位（JSONB 数组：执行时需填充的输入）';

COMMENT ON COLUMN sops.status IS '状态：draft（草稿）/ published（已发布）/ archived（已归档）';

COMMENT ON COLUMN sops.version IS '当前版本号（发布时自增并落 sop_versions 快照）';

COMMENT ON COLUMN sops.owner_id IS '归属账号（创建者用户名）';

COMMENT ON COLUMN sops.environment IS '环境: draft-调试草稿(工作台编辑), production-线上发布(运行时注入)；同一 SOP 两环境各存一行，promote 时草稿覆盖线上并写版本快照';

COMMENT ON COLUMN sops.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN sops.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- sops 环境隔离（changelog 20260915/01，等价 alembic 0030）----
-- 幂等：加列 + CHECK + 主键重建 (tenant_id,id) → (tenant_id,id,environment)
ALTER TABLE sops ADD COLUMN IF NOT EXISTS
    environment VARCHAR(16) NOT NULL DEFAULT 'production';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_sops_environment'
    ) THEN
        ALTER TABLE sops ADD CONSTRAINT ck_sops_environment
            CHECK (environment IN ('draft', 'production'));
    END IF;
END
$$;

ALTER TABLE sops DROP CONSTRAINT IF EXISTS pk_sops;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'pk_sops'
    ) THEN
        ALTER TABLE sops ADD CONSTRAINT pk_sops
            PRIMARY KEY (tenant_id, id, environment);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_sops_owner_env
    ON sops (tenant_id, owner_id, environment);

-- ---- team_run_nodes ----

COMMENT ON COLUMN team_run_nodes.run_id IS '所属运行 ID（team_runs.id）';

COMMENT ON COLUMN team_run_nodes.node_key IS 'DAG 节点键（run 内唯一，与 tenant/run 组成联合主键）';

COMMENT ON COLUMN team_run_nodes.assignee_expert_id IS '受派专家 ID（空串表示未分派或非专家节点）';

COMMENT ON COLUMN team_run_nodes.assignee_user_id IS '受派人用户 ID（人工任务节点，可为 NULL）';

COMMENT ON COLUMN team_run_nodes.node_type IS '节点类型（默认 task：专家任务节点）';

COMMENT ON COLUMN team_run_nodes.status IS '节点状态（默认 pending：pending/running/done/failed 等）';

COMMENT ON COLUMN team_run_nodes.contract IS '任务契约（JSONB：中央大脑下发的 TaskContract）';

COMMENT ON COLUMN team_run_nodes.result IS '结果契约（JSONB：成员专家返回的 ResultContract）';

COMMENT ON COLUMN team_run_nodes.repair IS '修复契约（JSONB：最近一次 RepairContract）';

COMMENT ON COLUMN team_run_nodes.verdict IS '校验结论：PASS / FAIL / ESCALATE（空串表示未校验）';

COMMENT ON COLUMN team_run_nodes.repair_count IS '修复次数';

COMMENT ON COLUMN team_run_nodes.session_id IS '节点执行所用会话 ID（可回查会话明细）';

COMMENT ON COLUMN team_run_nodes.token_cost IS '节点消耗 token 数（计量汇总）';

COMMENT ON COLUMN team_run_nodes.attempt IS '执行轮次（每次委派自增，兼作崩溃恢复游标）';

COMMENT ON COLUMN team_run_nodes.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN team_run_nodes.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN team_run_nodes.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- team_runs ----

COMMENT ON COLUMN team_runs.id IS '运行 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN team_runs.team_id IS '执行团队 ID（expert_teams.id）';

COMMENT ON COLUMN team_runs.project_id IS '归属项目 ID（可为 NULL 表示个人或临时运行）';

COMMENT ON COLUMN team_runs.source_chat_id IS '发起会话 ID（可为 NULL 表示 API 直发起）';

COMMENT ON COLUMN team_runs.initiator_id IS '发起人（用户名）';

COMMENT ON COLUMN team_runs.status IS '运行状态机：planning → awaiting_confirm → running → verifying/repairing → aggregating → done/failed/escalated/canceled/interrupted';

COMMENT ON COLUMN team_runs.goal IS '团队目标（用户输入的任务目标）';

COMMENT ON COLUMN team_runs.plan IS '中央大脑计划（JSONB：PlanContract 快照，含 DAG）';

COMMENT ON COLUMN team_runs.policy IS '执行策略（JSONB：验证/修复/升级策略）';

COMMENT ON COLUMN team_runs.context_bundle IS '上下文包（JSONB：注入成员的共享上下文快照）';

COMMENT ON COLUMN team_runs.context_version IS '上下文版本号（replan 时递增）';

COMMENT ON COLUMN team_runs.summary IS '运行总结（聚合阶段产出）';

COMMENT ON COLUMN team_runs.result IS '最终交付（JSONB）';

COMMENT ON COLUMN team_runs.clarification IS '澄清信息（JSONB：awaiting_confirm 时向用户收集）';

COMMENT ON COLUMN team_runs.repair_count IS '全局修复次数';

COMMENT ON COLUMN team_runs.replan_count IS '重规划次数';

COMMENT ON COLUMN team_runs.error IS '失败原因（成功为空串）';

COMMENT ON COLUMN team_runs.escalation_reason IS '升级原因（escalated 时填写的人工介入说明）';

COMMENT ON COLUMN team_runs.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN team_runs.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN team_runs.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ---- xian_workspaces ----

COMMENT ON COLUMN xian_workspaces.id IS '工作区 ID（业务侧生成，与 tenant_id 组成联合主键）';

COMMENT ON COLUMN xian_workspaces.owner_id IS '属主用户名';

COMMENT ON COLUMN xian_workspaces.name IS '工作区名称（侧边栏展示名）';

COMMENT ON COLUMN xian_workspaces.dir_path IS '工作区磁盘目录路径（规范化后的绝对路径，与 owner 组合唯一）';

COMMENT ON COLUMN xian_workspaces.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN xian_workspaces.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN xian_workspaces.updated_at IS '更新时间（DB 自动维护，UTC）';


-- ============================================================
-- 20260909/01 agent_documents（数字员工档案文档表，alembic 0014 等价）
-- ============================================================

-- ============================================================
-- agent_documents：数字员工档案文档表
-- alembic 等价路径：0014_agent_documents
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_documents (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    id           BIGSERIAL PRIMARY KEY,
    agent_id     VARCHAR(64) NOT NULL,
    doc_type     VARCHAR(32) NOT NULL,
    environment  VARCHAR(16) NOT NULL DEFAULT 'production',
    content      TEXT NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    version      INTEGER NOT NULL DEFAULT 1,
    updated_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_documents_doc
        UNIQUE (tenant_id, agent_id, doc_type, environment),
    CONSTRAINT ck_agent_documents_doc_type
        CHECK (doc_type IN ('profile', 'agents', 'soul', 'agent_json')),
    CONSTRAINT ck_agent_documents_environment
        CHECK (environment IN ('draft', 'production'))
);

CREATE INDEX IF NOT EXISTS idx_agent_documents_agent
    ON agent_documents (tenant_id, agent_id);

COMMENT ON TABLE agent_documents IS '数字员工档案文档表：PROFILE/AGENTS/SOUL/agent.json 的 PG 权威存储（Phase A 影子双写，Phase B 读切换；environment 区分草稿/生产）';

COMMENT ON COLUMN agent_documents.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN agent_documents.id IS '文档行 ID（BIGSERIAL 自增主键）';

COMMENT ON COLUMN agent_documents.agent_id IS '智能体标识（工作区目录名，与 AgentProfileRef.id 一致）';

COMMENT ON COLUMN agent_documents.doc_type IS '文档类型: profile-PROFILE.md, agents-AGENTS.md, soul-SOUL.md, agent_json-agent.json';

COMMENT ON COLUMN agent_documents.environment IS '环境: draft-调试草稿, production-线上发布';

COMMENT ON COLUMN agent_documents.content IS '文档全文内容';

COMMENT ON COLUMN agent_documents.content_hash IS '内容 SHA-256 摘要（幂等 upsert 判据，内容未变时不递增版本）';

COMMENT ON COLUMN agent_documents.version IS '文档版本号，内容变更时单调递增';

COMMENT ON COLUMN agent_documents.updated_by IS '最后修改人标识';

COMMENT ON COLUMN agent_documents.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN agent_documents.updated_at IS '更新时间（DB 自动维护，UTC）';


-- ============================================================
-- 20260909/02 audit_events（治理审计事件表，alembic 0015 等价）
-- ============================================================

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


-- ============================================================
-- 20260909/03 chats/session_states 增加 agent_id 维度
-- （数字员工会话隔离；alembic 等价路径：0016_chats_agent_scope）
-- ============================================================

-- chats：归属智能体列 + 复合索引
ALTER TABLE chats ADD COLUMN IF NOT EXISTS agent_id
VARCHAR(128) NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS ix_chats_tenant_agent
ON chats (tenant_id, agent_id);

COMMENT ON COLUMN chats.agent_id IS
'归属智能体标识（数字员工会话隔离；历史行由 backfill_chat_agent 修正）';

-- session_states：归属智能体列 + 主键扩展
ALTER TABLE session_states ADD COLUMN IF NOT EXISTS agent_id
VARCHAR(128) NOT NULL DEFAULT 'default';

ALTER TABLE session_states DROP CONSTRAINT IF EXISTS pk_session_states;

ALTER TABLE session_states ADD CONSTRAINT pk_session_states
PRIMARY KEY (tenant_id, agent_id, channel, owner_id, session_id);

COMMENT ON COLUMN session_states.agent_id IS
'归属智能体标识（数字员工会话状态隔离）';

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

-- ============================================================================
-- 20260909/05 模型提供商配置落库平面（provider_configs + model_active_slots）
-- ============================================================================

-- 模型提供商配置表（api_key 密文提升列 + 整包快照 JSONB）
CREATE TABLE IF NOT EXISTS provider_configs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    api_key_encrypted TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot JSONB NOT NULL DEFAULT '{}',
    snapshot_schema_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_configs PRIMARY KEY (tenant_id, provider_id)
);

-- 模型槽位表（承接 active_llm；slot_name 现阶段固定 llm）
CREATE TABLE IF NOT EXISTS model_active_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    slot_name VARCHAR(32) NOT NULL,
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_model_active_slots PRIMARY KEY (tenant_id, slot_name)
);

COMMENT ON TABLE provider_configs IS
'模型提供商配置落库平面（api_key 以 ENC: 密文存储，snapshot 为整包 provider 快照 JSONB）';
COMMENT ON COLUMN provider_configs.api_key_encrypted IS
'Fernet 加密后的 API Key（ENC: 前缀，主密钥见 secret_store）';
COMMENT ON COLUMN provider_configs.enabled IS
'厂商启用状态（镜像控制台语义：需要 key 且未配置即停用）';
COMMENT ON COLUMN provider_configs.snapshot IS
'整包 provider 快照（extra_models/discovered_models/hidden_model_ids/removed_model_ids 等，不含 api_key 明文）';
COMMENT ON TABLE model_active_slots IS
'模型槽位表（承接 active_llm；slot_name 现阶段固定 llm）';
COMMENT ON COLUMN model_active_slots.slot_name IS
'槽位名: llm（预留 embedding 等）';

-- ============================================================================
-- 20260909/06 供应商模型行级表（provider_models）
-- ============================================================================

CREATE TABLE IF NOT EXISTS provider_models (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    provider_id VARCHAR(64) NOT NULL,
    model_id VARCHAR(128) NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    source VARCHAR(16) NOT NULL DEFAULT 'builtin',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_free BOOLEAN NOT NULL DEFAULT FALSE,
    supports_multimodal BOOLEAN,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_provider_models
        PRIMARY KEY (tenant_id, provider_id, model_id)
);

COMMENT ON TABLE provider_models IS
'供应商模型行级表（每厂商每模型一行，参数独立；由 provider_configs.snapshot 每次变更自动投影同步）';
COMMENT ON COLUMN provider_models.model_id IS
'模型 ID（如 qwen3.7-max）';
COMMENT ON COLUMN provider_models.source IS
'模型来源: builtin(内置目录), user(用户添加), discovered(自动发现)';
COMMENT ON COLUMN provider_models.enabled IS
'启用开关（false=已禁用：保留配置但从所有选择器隐藏）';
COMMENT ON COLUMN provider_models.config IS
'模型级参数（generate_kwargs/config_overrides/thinking/max_input_length 等全部其余字段）';

-- 数字员工默认模型槽位表（每员工每槽位一行，slot_name 现阶段固定 llm）
CREATE TABLE IF NOT EXISTS agent_model_slots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    slot_name VARCHAR(32) NOT NULL DEFAULT 'llm',
    provider_id VARCHAR(64) NOT NULL DEFAULT '',
    model VARCHAR(128) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_model_slots PRIMARY KEY (tenant_id, agent_id, slot_name)
);

COMMENT ON TABLE agent_model_slots IS
'数字员工默认模型槽位表（后台档案区为每个员工配置的默认运行模型；agent.json active_model 的 PG 落库平面，运行时解析优先级：本表 → agent.json → 全局 active_llm）';
COMMENT ON COLUMN agent_model_slots.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN agent_model_slots.agent_id IS
'数字员工 ID（智能体档案 ID，如 python-fullstack）';
COMMENT ON COLUMN agent_model_slots.slot_name IS
'槽位名: llm（预留 embedding 等槽位）';
COMMENT ON COLUMN agent_model_slots.provider_id IS
'模型提供商 ID（如 aliyun-codingplan；空串视为未配置，解析时跳过本表回退 agent.json）';
COMMENT ON COLUMN agent_model_slots.model IS
'模型 ID（如 GLM-5.3-Flash；空串视为未配置）';
COMMENT ON COLUMN agent_model_slots.created_at IS
'创建时间（首次配置默认模型时写入）';
COMMENT ON COLUMN agent_model_slots.updated_at IS
'更新时间（每次切换默认模型时刷新）';

-- 模型参数档案化（数字员工详情页专属配置；一行=员工×模型参数档案，
-- 切换模型即切换激活档案，切回自动恢复历史参数；NULL=跟随全局基线）
ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS config JSONB;

COMMENT ON COLUMN agent_model_slots.config IS
'模型参数档案 JSONB（max_input_length/thinking_enabled/thinking_budget/reasoning_effort；NULL 或字段缺省=跟随全局基线；归属该行的 provider_id+model）';

ALTER TABLE agent_model_slots
    DROP CONSTRAINT IF EXISTS pk_agent_model_slots;

ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE agent_model_slots SET is_active = TRUE WHERE NOT is_active;

ALTER TABLE agent_model_slots
    ADD CONSTRAINT pk_agent_model_slots
    PRIMARY KEY (tenant_id, agent_id, slot_name, provider_id, model);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_model_slots_active
    ON agent_model_slots (tenant_id, agent_id, slot_name) WHERE is_active;

COMMENT ON COLUMN agent_model_slots.is_active IS
'激活状态位：当前生效的模型档案；同一员工同一槽位至多一行 TRUE';


-- ============================================================
-- 20260910/02 agent_document_revisions（档案文档版本快照表，alembic 0022 等价）
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_document_revisions (
    tenant_id    VARCHAR(64) NOT NULL DEFAULT 'default',
    id           BIGSERIAL PRIMARY KEY,
    agent_id     VARCHAR(64) NOT NULL,
    doc_type     VARCHAR(32) NOT NULL,
    environment  VARCHAR(16) NOT NULL DEFAULT 'production',
    version      INTEGER NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    published_by TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_document_revisions_version
        UNIQUE (tenant_id, agent_id, doc_type, environment, version),
    CONSTRAINT ck_agent_document_revisions_doc_type
        CHECK (doc_type IN ('profile', 'agents', 'soul', 'agent_json')),
    CONSTRAINT ck_agent_document_revisions_environment
        CHECK (environment IN ('draft', 'production'))
);

CREATE INDEX IF NOT EXISTS idx_agent_document_revisions_doc
    ON agent_document_revisions (tenant_id, agent_id, doc_type);

COMMENT ON TABLE agent_document_revisions IS '数字员工档案文档版本快照表：发布/回滚每次变更 production 行时插入不可变快照，每文档惰性保留最近 20 版';

COMMENT ON COLUMN agent_document_revisions.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';

COMMENT ON COLUMN agent_document_revisions.id IS '快照行 ID（BIGSERIAL 自增主键）';

COMMENT ON COLUMN agent_document_revisions.agent_id IS '智能体标识（工作区目录名，与 AgentProfileRef.id 一致）';

COMMENT ON COLUMN agent_document_revisions.doc_type IS '文档类型: profile-PROFILE.md, agents-AGENTS.md, soul-SOUL.md, agent_json-agent.json';

COMMENT ON COLUMN agent_document_revisions.environment IS '环境: draft-调试草稿, production-线上发布';

COMMENT ON COLUMN agent_document_revisions.version IS '快照对应的生产行版本号（与 agent_documents.version 同源）';

COMMENT ON COLUMN agent_document_revisions.content IS '快照文档全文内容';

COMMENT ON COLUMN agent_document_revisions.content_hash IS '内容 SHA-256 摘要';

COMMENT ON COLUMN agent_document_revisions.published_by IS '发布/回滚操作人标识';

COMMENT ON COLUMN agent_document_revisions.published_at IS '快照时间（DB 自动维护，UTC）';


-- ============================================================
-- 20260911/01 skill_pg_plane（技能 PG 落库平面三表：目录/绑定/快照，alembic 0023/0024/0025 等价）
-- ============================================================

-- ① 技能池目录表（平台技能池的 PG 元数据权威平面）
CREATE TABLE IF NOT EXISTS skill_catalog (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    skill_name VARCHAR(128) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'customized',
    installed_from VARCHAR(128) NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    version_text VARCHAR(64) NOT NULL DEFAULT '',
    emoji VARCHAR(16) NOT NULL DEFAULT '',
    builtin_language VARCHAR(8) NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]',
    config JSONB NOT NULL DEFAULT '{}',
    automation JSONB NOT NULL DEFAULT '{}',
    external BOOLEAN NOT NULL DEFAULT FALSE,
    external_path TEXT NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    display_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    description_zh TEXT NOT NULL DEFAULT '',
    protected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_skill_catalog PRIMARY KEY (tenant_id, skill_name)
);

COMMENT ON TABLE skill_catalog IS
'技能池目录表（平台技能池的 PG 元数据权威平面：名称/来源/版本/标签/池级配置/自动化策略/中文映射；skill_pool/skill.json manifest 的逐条目投影，json 后端零动作、dual 影子写、pg 权威读）';
COMMENT ON COLUMN skill_catalog.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN skill_catalog.skill_name IS
'技能名（skill_pool 下的目录名，同 manifest 键）';
COMMENT ON COLUMN skill_catalog.source IS
'技能来源: builtin-内置, customized-自定义/市场安装';
COMMENT ON COLUMN skill_catalog.installed_from IS
'安装来源标识（hub 来源: skills-sh/github/lobehub/qwenpaw/modelscope/aliyun/skillsmp/clawhub/url/zip；空串=本地创建）';
COMMENT ON COLUMN skill_catalog.source_url IS
'市场原始地址（hub 安装时记录，便于溯源与更新检查）';
COMMENT ON COLUMN skill_catalog.version_text IS
'技能版本（SKILL.md frontmatter version）';
COMMENT ON COLUMN skill_catalog.emoji IS
'技能图标 emoji（metadata.qwenpaw.emoji）';
COMMENT ON COLUMN skill_catalog.builtin_language IS
'内置技能语言变体: en/zh（非内置为空串）';
COMMENT ON COLUMN skill_catalog.tags IS
'标签数组 JSONB（如 ["文档","办公"]）';
COMMENT ON COLUMN skill_catalog.config IS
'池级环境变量配置 JSONB（装配到员工时随行下发）';
COMMENT ON COLUMN skill_catalog.automation IS
'自动化策略 JSONB（auto_update/auto_sync/targets/synced_hash；引用化后 auto_sync 语义退役仅作兼容保留）';
COMMENT ON COLUMN skill_catalog.external IS
'是否外部目录技能（skill_paths 额外根，只读）';
COMMENT ON COLUMN skill_catalog.external_path IS
'外部技能目录绝对路径（external=true 时有效）';
COMMENT ON COLUMN skill_catalog.content_hash IS
'技能体内容指纹（SKILL.md sha256；空串=待对账/内容丢失）';
COMMENT ON COLUMN skill_catalog.display_name_zh IS
'中文显示名映射（技能卡片优先展示；空串回退英文 name）';
COMMENT ON COLUMN skill_catalog.description_zh IS
'中文描述映射（面向中文用户的一句话解释；空串回退英文描述）';
COMMENT ON COLUMN skill_catalog.protected IS
'是否受保护（禁止删除）';
COMMENT ON COLUMN skill_catalog.created_at IS
'创建时间（首次入池时写入）';
COMMENT ON COLUMN skill_catalog.updated_at IS
'更新时间（每次技能变更时刷新）';

-- ② 数字员工技能绑定表（员工显式装配的技能引用；装配=写一行绑定，技能体零拷贝）
CREATE TABLE IF NOT EXISTS agent_skill_bindings (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    skill_name VARCHAR(128) NOT NULL,
    origin VARCHAR(16) NOT NULL DEFAULT 'pool',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    channels JSONB NOT NULL DEFAULT '["all"]',
    config JSONB NOT NULL DEFAULT '{}',
    tags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_skill_bindings PRIMARY KEY (tenant_id, agent_id, skill_name)
);

COMMENT ON TABLE agent_skill_bindings IS
'数字员工技能绑定表（员工显式装配的技能引用；workspace skill.json manifest 的 PG 落库平面，装配动作只写绑定行、技能体零拷贝，运行时解析优先级：私有自建 → 池 → 内置）';
COMMENT ON COLUMN agent_skill_bindings.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN agent_skill_bindings.agent_id IS
'数字员工 ID（智能体档案 ID，如 python-fullstack）';
COMMENT ON COLUMN agent_skill_bindings.skill_name IS
'技能名（池内技能目录名或员工私有技能名）';
COMMENT ON COLUMN agent_skill_bindings.origin IS
'装配来源: pool-从技能池引用, builtin-内置技能, private-员工私有自建';
COMMENT ON COLUMN agent_skill_bindings.enabled IS
'是否启用（禁用后该技能不注入员工运行时）';
COMMENT ON COLUMN agent_skill_bindings.channels IS
'生效渠道数组 JSONB（["all"] 或 ["console","dingtalk"...]）';
COMMENT ON COLUMN agent_skill_bindings.config IS
'员工级环境变量覆盖 JSONB（覆盖池级 config 同名字段）';
COMMENT ON COLUMN agent_skill_bindings.tags IS
'员工级标签 JSONB（可空，随池同步）';
COMMENT ON COLUMN agent_skill_bindings.created_at IS
'创建时间（首次装配时写入）';
COMMENT ON COLUMN agent_skill_bindings.updated_at IS
'更新时间（每次装配变更时刷新）';

-- ③ 技能体内容快照表（技能目录 zip 冷备；文件丢失时启动对账自动解压物化自愈）
CREATE TABLE IF NOT EXISTS skill_content_snapshots (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    owner_agent_id VARCHAR(64) NOT NULL DEFAULT '',
    skill_name VARCHAR(128) NOT NULL,
    content_zip BYTEA NOT NULL,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_skill_content_snapshots PRIMARY KEY (tenant_id, owner_agent_id, skill_name)
);

COMMENT ON TABLE skill_content_snapshots IS
'技能体内容快照表（技能目录 zip 冷备；文件丢失时启动对账自动解压物化自愈，实现恢复数据库=完整恢复）';
COMMENT ON COLUMN skill_content_snapshots.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN skill_content_snapshots.owner_agent_id IS
'归属员工 ID（空串=技能池快照；员工 ID=该员工私有技能快照）';
COMMENT ON COLUMN skill_content_snapshots.skill_name IS
'技能名（同 skill_pool 目录名或 workspace 私有技能名）';
COMMENT ON COLUMN skill_content_snapshots.content_zip IS
'技能体 zip 字节（SKILL.md+references/+scripts/，继承 200MB 上限，排除 OS 缓存伪影）';
COMMENT ON COLUMN skill_content_snapshots.content_hash IS
'快照对应 SKILL.md sha256（与 skill_catalog.content_hash 对齐校验快照新旧，漂移时以文件为准重打）';
COMMENT ON COLUMN skill_content_snapshots.created_at IS
'创建时间（首次打快照时写入）';
COMMENT ON COLUMN skill_content_snapshots.updated_at IS
'更新时间（技能体每次变更重打快照时刷新）';

-- ⑪ open API 幂等回放缓存表（/api/open 调用携带 Idempotency-Key 时缓存响应，同 key+幂等键+同指纹重放直接回放，TTL 24h；同指纹不同请求体拒绝 409）
CREATE TABLE IF NOT EXISTS open_api_idempotency (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    key_id VARCHAR(64) NOT NULL,
    idem_key VARCHAR(128) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL DEFAULT '',
    status_code INTEGER NOT NULL DEFAULT 200,
    response_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_open_api_idempotency PRIMARY KEY (tenant_id, key_id, idem_key)
);

COMMENT ON TABLE open_api_idempotency IS
'open API 幂等回放缓存表（/api/open 调用携带 Idempotency-Key 时缓存响应，同 key+幂等键+同指纹重放直接回放，TTL 24h；同指纹不同请求体拒绝 409）';
COMMENT ON COLUMN open_api_idempotency.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN open_api_idempotency.key_id IS
'API 密钥 ID（expert_api_keys.id，幂等作用域=单密钥）';
COMMENT ON COLUMN open_api_idempotency.idem_key IS
'幂等键（调用方 Idempotency-Key header，≤128 字符）';
COMMENT ON COLUMN open_api_idempotency.fingerprint IS
'请求指纹（请求体规范化 JSON 的 sha256，用于同键不同体冲突检测）';
COMMENT ON COLUMN open_api_idempotency.status_code IS
'缓存响应的状态码（200/503 等，回放时原样返回）';
COMMENT ON COLUMN open_api_idempotency.response_json IS
'缓存响应体 JSON（首次执行的完整响应）';
COMMENT ON COLUMN open_api_idempotency.created_at IS
'创建时间（首次执行完成时写入）';
COMMENT ON COLUMN open_api_idempotency.expires_at IS
'过期时间（创建 + 24h；查询侧懒过滤，过期条目由清理任务或下次写入同键时覆盖）';

CREATE INDEX IF NOT EXISTS idx_open_api_idempotency_expires
    ON open_api_idempotency (expires_at);

-- ⑫ open API 调用审计流水表（/api/open 全量请求留痕，含 4xx/5xx；审计写入 best-effort 不阻塞业务）
CREATE TABLE IF NOT EXISTS open_api_audit (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    key_id VARCHAR(64) NOT NULL DEFAULT '',
    expert_id VARCHAR(64) NOT NULL DEFAULT '',
    method VARCHAR(8) NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    status_code INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    idem_key VARCHAR(128) NOT NULL DEFAULT '',
    client_ip VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_open_api_audit PRIMARY KEY (tenant_id, id)
);

COMMENT ON TABLE open_api_audit IS
'open API 调用审计流水表（/api/open 全量请求留痕，含 4xx/5xx；审计写入 best-effort 不阻塞业务）';
COMMENT ON COLUMN open_api_audit.tenant_id IS
'租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN open_api_audit.id IS
'审计条目 ID（oaadt_ 前缀雪花风格）';
COMMENT ON COLUMN open_api_audit.key_id IS
'API 密钥 ID（鉴权成功后回填；空串=鉴权失败前的请求）';
COMMENT ON COLUMN open_api_audit.expert_id IS
'目标员工 ID（从路径参数提取；空串=无法提取）';
COMMENT ON COLUMN open_api_audit.method IS
'HTTP 方法（GET/POST/...）';
COMMENT ON COLUMN open_api_audit.path IS
'请求路径（含员工 ID 等路径参数）';
COMMENT ON COLUMN open_api_audit.status_code IS
'响应状态码（0=未产生响应即中断）';
COMMENT ON COLUMN open_api_audit.latency_ms IS
'请求耗时毫秒数';
COMMENT ON COLUMN open_api_audit.idem_key IS
'请求携带的幂等键（未携带为空串）';
COMMENT ON COLUMN open_api_audit.client_ip IS
'客户端 IP（X-Forwarded-For 首段优先）';
COMMENT ON COLUMN open_api_audit.created_at IS
'请求完成时间';

CREATE INDEX IF NOT EXISTS idx_open_api_audit_key_time
    ON open_api_audit (tenant_id, key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_open_api_audit_expert_time
    ON open_api_audit (tenant_id, expert_id, created_at DESC);


-- ============================================================
-- 20260913/01 cron_jobs_pg（定时任务 PG 权威平面，alembic 0027 等价）
-- ============================================================

CREATE TABLE IF NOT EXISTS cron_jobs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    job_id VARCHAR(128) NOT NULL,
    spec JSONB NOT NULL,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cron_jobs_job UNIQUE (tenant_id, agent_id, job_id)
);

COMMENT ON TABLE cron_jobs IS
'数字员工定时任务规格权威表（jobs.json 单文件平面的 PG 权威化，spec 为 CronJobSpec 完整序列化；json 后端零动作、dual/pg 权威，文件降级为投影缓存）';

COMMENT ON COLUMN cron_jobs.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';

COMMENT ON COLUMN cron_jobs.agent_id IS '数字员工 ID（workspace 目录名，与 agent_documents 同约定）';

COMMENT ON COLUMN cron_jobs.job_id IS '任务 ID（CronJobSpec.id，jobs.json 内唯一）';

COMMENT ON COLUMN cron_jobs.spec IS '任务规格完整序列化 JSONB（schedule/dispatch/runtime/text 等全量载荷，权威数据源）';

COMMENT ON COLUMN cron_jobs.content_hash IS '规格载荷 SHA-256（幂等 upsert 判定，内容不变零写放大）';

COMMENT ON COLUMN cron_jobs.enabled IS '是否启用（spec.enabled 的冗余可查询投影，便于运维检索停用任务）';

COMMENT ON COLUMN cron_jobs.created_at IS '创建时间（首次写入时生成）';

COMMENT ON COLUMN cron_jobs.updated_at IS '更新时间（每次内容变更时刷新）';

CREATE TABLE IF NOT EXISTS cron_job_history (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    job_id VARCHAR(128) NOT NULL,
    seq BIGINT NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    error TEXT,
    trigger VARCHAR(16) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cron_job_history_seq
        UNIQUE (tenant_id, agent_id, job_id, seq)
);

COMMENT ON TABLE cron_job_history IS
'定时任务执行历史表（append-only，per-job 单调 seq 排序，超限惰性修剪）';

COMMENT ON COLUMN cron_job_history.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';

COMMENT ON COLUMN cron_job_history.agent_id IS '数字员工 ID（workspace 目录名）';

COMMENT ON COLUMN cron_job_history.job_id IS '任务 ID（CronJobSpec.id）';

COMMENT ON COLUMN cron_job_history.seq IS '每任务单调递增序号（新→旧读取与保留窗口修剪的排序键）';

COMMENT ON COLUMN cron_job_history.run_at IS '执行时间（timestamptz，naive 输入按 UTC 归一）';

COMMENT ON COLUMN cron_job_history.status IS '执行状态: success-成功, error-失败, running-执行中, skipped-跳过, cancelled-取消';

COMMENT ON COLUMN cron_job_history.error IS '失败原因（成功/跳过原因为空或跳过说明）';

COMMENT ON COLUMN cron_job_history.trigger IS '触发方式: scheduled-定时触发, manual-手动触发';

COMMENT ON COLUMN cron_job_history.created_at IS '入库时间';

CREATE INDEX IF NOT EXISTS ix_cron_jobs_agent
    ON cron_jobs (tenant_id, agent_id);
CREATE INDEX IF NOT EXISTS ix_cron_job_history_job
    ON cron_job_history (tenant_id, agent_id, job_id);


-- ============================================================
-- 20260913/02 inbox_events_pg（收件箱事件 PG 权威平面 + 可移植应用密钥，alembic 0028 等价）
-- ============================================================

CREATE TABLE IF NOT EXISTS inbox_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    event_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(64) NOT NULL DEFAULT 'default',
    source_type VARCHAR(32) NOT NULL DEFAULT '',
    source_id VARCHAR(128) NOT NULL DEFAULT '',
    event_type VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT '',
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inbox_events_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS ix_inbox_events_agent
    ON inbox_events (tenant_id, agent_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_inbox_events_source
    ON inbox_events (tenant_id, source_type);

COMMENT ON TABLE inbox_events IS
'收件箱通知事件权威表（inbox_events.json 单文件平面的 PG 权威化，append-only 事件流；json 后端零动作、dual/pg 权威，文件仅一次性 backfill 种子）';

COMMENT ON COLUMN inbox_events.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';

COMMENT ON COLUMN inbox_events.event_id IS '事件 ID（UUID，原 json 平面的 id 字段，租户内唯一）';

COMMENT ON COLUMN inbox_events.agent_id IS '数字员工 ID（default 表示全局事件）';

COMMENT ON COLUMN inbox_events.source_type IS '事件来源类型（cron/mailbox/skill 等，控制台过滤维度）';

COMMENT ON COLUMN inbox_events.source_id IS '来源实体 ID（如任务 ID、邮件 ID，可为空串）';

COMMENT ON COLUMN inbox_events.event_type IS '事件业务类型（created/failed/run_finished 等）';

COMMENT ON COLUMN inbox_events.status IS '事件状态（payload 演进的可查询投影，控制台筛选用）';

COMMENT ON COLUMN inbox_events.severity IS '严重级别: info-信息, warning-警告, error-错误';

COMMENT ON COLUMN inbox_events.title IS '事件标题（控制台列表展示）';

COMMENT ON COLUMN inbox_events.body IS '事件正文（控制台详情展示）';

COMMENT ON COLUMN inbox_events.payload IS '事件扩展载荷 JSONB（run_id/acl_sender_address 等结构化上下文）';

COMMENT ON COLUMN inbox_events.is_read IS '是否已读（布尔投影，未读计数与全部已读操作的目标列）';

COMMENT ON COLUMN inbox_events.created_at IS '事件时间（Unix 浮点秒，与原 json 平面字段语义一致）';

COMMENT ON COLUMN inbox_events.updated_at IS '入库/更新时间（已读标记等操作时刷新）';

CREATE TABLE IF NOT EXISTS app_portable_keys (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    key_name VARCHAR(64) NOT NULL,
    key_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_app_portable_keys UNIQUE (tenant_id, key_name)
);

COMMENT ON TABLE app_portable_keys IS
'可移植应用级加密密钥表（跨设备可解密密文的密钥材料，安全边界等价于 PG 自身访问控制；与 OS keychain 绑定的本机 master key 互补）';

COMMENT ON COLUMN app_portable_keys.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';

COMMENT ON COLUMN app_portable_keys.key_name IS '密钥用途名（provider_api_key 为厂商 api_key 可移植加密密钥）';

COMMENT ON COLUMN app_portable_keys.key_value IS '密钥材料本体（Fernet key 的 base64 编码；泄露面=PG 访问权）';

COMMENT ON COLUMN app_portable_keys.created_at IS '创建时间（首次使用时生成）';

COMMENT ON COLUMN app_portable_keys.updated_at IS '更新时间（预留轮换场景）';

-- [同步�?db/feature/agent_run_logs_20260908/test.sql] �?
-- [同步�?db/feature/agent_run_logs_20260908/prod.sql] �?
-- [等价 alembic] 0029_cron_task_ledger_unify

-- 台账来源列（存量行默�?ui，与历史 UI 创建语义一致）
ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS
source VARCHAR(16) NOT NULL DEFAULT 'ui';

ALTER TABLE expert_scheduled_tasks ADD COLUMN IF NOT EXISTS
origin JSONB NOT NULL DEFAULT '{}';

-- 执行记录运行关联列（存量历史行空串，详情回退摘要展示�?
ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS
run_id VARCHAR(64) NOT NULL DEFAULT '';

ALTER TABLE expert_task_runs ADD COLUMN IF NOT EXISTS
session_id TEXT NOT NULL DEFAULT '';

-- 运行日志定时任务反查键（会话执行�?NULL�?
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS
cron_job_id VARCHAR(64);

-- source 枚举约束（PG �?ADD CONSTRAINT IF NOT EXISTS，按名称幂等判定�?
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_expert_scheduled_tasks_source'
    ) THEN
        ALTER TABLE expert_scheduled_tasks ADD CONSTRAINT
        ck_expert_scheduled_tasks_source
        CHECK (source IN ('ui', 'chat', 'api'));
    END IF;
END
$$;

-- 台账按来源筛选索�?
CREATE INDEX IF NOT EXISTS idx_expert_scheduled_tasks_source
ON expert_scheduled_tasks (tenant_id, expert_id, source);

-- 执行记录 �?运行详情跳转键（空串历史行不进索引）
CREATE INDEX IF NOT EXISTS idx_expert_task_runs_run
ON expert_task_runs (tenant_id, run_id) WHERE run_id <> '';

-- 运行日志按定时任务反查索�?
CREATE INDEX IF NOT EXISTS ix_agent_runs_cron_job
ON agent_runs (tenant_id, cron_job_id, started_at)
WHERE cron_job_id IS NOT NULL;

COMMENT ON COLUMN expert_scheduled_tasks.source IS
'任务来源: ui-界面创建, chat-对话创建, api-开放接口创建（注册观察者自动投影，统一台账单一出口�?;
COMMENT ON COLUMN expert_scheduled_tasks.origin IS
'来源端原始载荷投�?JSONB（对话创建时保留 CronJobSpec 关键字段�?dispatch/channel，便于溯源）';
COMMENT ON COLUMN expert_task_runs.run_id IS
'关联 agent_runs 的运�?ID（详情层复用会话日志权威结构：span �?+ 会话回放；历史行为空串）';
COMMENT ON COLUMN expert_task_runs.session_id IS
'本次执行落库的会�?ID（share_session=false 时为 cron:{job_id} 独立会话�?;
COMMENT ON COLUMN agent_runs.cron_job_id IS
'定时任务 ID（source=cron 的执行反查键；会话执行为 NULL�?;

-- [变更说明] 数字员工治理平面（employee_governance）：
--            1) 新建 employee_governance 表，作为「归属部门 + 可见范围」的唯一权威
--               （覆盖 agent / expert / team / 未来 workflow 四种形态，按运行时
--               agent_id 主键治理）；
--            2) visibility 三级：org-全员共享 / department-部门专属 / private-仅创建者；
--               granted_departments 记录额外授权部门（可见集合 = 归属 ∪ 授权）；
--            3) 从 experts 现有 visibility / department 回填一次治理行
--               （department 文本按 departments.name 匹配 id，匹配不上留 NULL）；
--            4) 运行期鉴权零改动：治理写入由服务层投影到 RBAC agent_grants
--               （部门已镜像为 dept:{path} team），本表不参与请求路径。
-- [变更时间] 2026-09-15
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0031_employee_governance

-- 建表幂等：新库直接建，存量库重复执行不报错
CREATE TABLE IF NOT EXISTS employee_governance (
    tenant_id           VARCHAR(64)  NOT NULL DEFAULT 'default',
    agent_id            VARCHAR(64)  NOT NULL,
    entity_kind         VARCHAR(16)  NOT NULL DEFAULT 'agent',
    entity_id           VARCHAR(64)  NOT NULL DEFAULT '',
    department_id       VARCHAR(64),
    visibility          VARCHAR(16)  NOT NULL DEFAULT 'org',
    granted_departments JSONB        NOT NULL DEFAULT '[]'::jsonb,
    owner_id            TEXT,
    updated_by          TEXT         NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_employee_governance PRIMARY KEY (tenant_id, agent_id)
);

-- CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_employee_governance_visibility'
    ) THEN
        ALTER TABLE employee_governance ADD CONSTRAINT
        ck_employee_governance_visibility
        CHECK (visibility IN ('org', 'department', 'private'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_employee_governance_kind'
    ) THEN
        ALTER TABLE employee_governance ADD CONSTRAINT
        ck_employee_governance_kind
        CHECK (entity_kind IN ('agent', 'expert', 'team', 'workflow'));
    END IF;
END
$$;

-- 控制台筛选维度的索引（按部门 / 按可见性 / 按形态聚合统计）
CREATE INDEX IF NOT EXISTS ix_employee_governance_department
    ON employee_governance (tenant_id, department_id);
CREATE INDEX IF NOT EXISTS ix_employee_governance_visibility
    ON employee_governance (tenant_id, visibility);
CREATE INDEX IF NOT EXISTS ix_employee_governance_kind
    ON employee_governance (tenant_id, entity_kind);

COMMENT ON TABLE employee_governance IS
    '数字员工治理表（归属部门 + 可见范围的唯一权威，覆盖 agent/expert/team/'
    'workflow 四种形态）；运行期鉴权走 RBAC agent_grants 投影，本表只做治理编辑面';
COMMENT ON COLUMN employee_governance.tenant_id IS
    '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN employee_governance.agent_id IS
    '运行时 agent 主键（default / expert_x / team_x / 未来 wf_x），与租户组成联合主键';
COMMENT ON COLUMN employee_governance.entity_kind IS
    '形态: agent-原生智能体(root config), expert-数字员工(专家), '
    'team-专家团, workflow-工作流(外部平台对接预留)';
COMMENT ON COLUMN employee_governance.entity_id IS
    '领域内主键（expert/team 用其业务 id；agent 与 agent_id 同值；workflow 预留）';
COMMENT ON COLUMN employee_governance.department_id IS
    '归属部门（逻辑外键 departments.id，NULL=未归属/平台级）；归属唯一';
COMMENT ON COLUMN employee_governance.visibility IS
    '可见范围: org-全员共享(所有部门可用), department-部门专属(仅归属∪授权部门可见可用), '
    'private-仅创建者';
COMMENT ON COLUMN employee_governance.granted_departments IS
    '额外授权部门 id 数组（visibility=department 时生效，实现"一份员工多方共享"）';
COMMENT ON COLUMN employee_governance.owner_id IS
    '归属人（visibility=private 的判定依据，取自领域记录的创建者）';
COMMENT ON COLUMN employee_governance.updated_by IS
    '最后一次治理操作的操作人（审计用）';
COMMENT ON COLUMN employee_governance.created_at IS
    '创建时间（首次治理时生成）';
COMMENT ON COLUMN employee_governance.updated_at IS
    '更新时间（每次治理变更刷新）';

-- 回填存量专家治理态：仅回填"非默认"的行（visibility≠org 或已填部门），
-- 无治理行 = 未归属 + 全员共享，注册表按该默认语义读取，避免全量灌入噪音行。
-- 幂等：ON CONFLICT DO NOTHING，重复执行零副作用。
INSERT INTO employee_governance (
    tenant_id, agent_id, entity_kind, entity_id,
    department_id, visibility, owner_id, updated_by
)
SELECT
    e.tenant_id,
    'expert_' || e.id,
    'expert',
    e.id,
    d.id,
    CASE WHEN e.visibility IN ('org', 'department', 'private')
         THEN e.visibility ELSE 'org' END,
    e.owner_id,
    'system_backfill'
FROM experts e
LEFT JOIN departments d
    ON d.tenant_id = e.tenant_id AND d.name = e.department
WHERE (e.visibility <> 'org' OR COALESCE(e.department, '') <> '')
ON CONFLICT (tenant_id, agent_id) DO NOTHING;


-- [变更说明] 账号体系 M2：qwenpaw_users + user_identity_bindings �?PG + agent_runs 用户筛选索�?
-- [变更时间] 2026-09-16
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步�?db/feature/agent_run_logs_20260908/test.sql] �?
-- [同步�?db/feature/agent_run_logs_20260908/prod.sql] �?
--
-- 背景：账号存储原�?users.json 文件（M1），项目已全�?PG 化后升级�?
-- PG 权威存储（接口不变，�?PG 部署继续走文件路径）。启动时对文�?
-- 存量账号做一次幂等导入�?
-- alembic twin: 0032_user_accounts_pg

-- 账号主表（username 不可变身份锚点：会话/记忆/运行日志按此归属�?
CREATE TABLE IF NOT EXISTS qwenpaw_users (
    tenant_id     VARCHAR(64)  NOT NULL DEFAULT 'default',
    username      VARCHAR(64)  NOT NULL,
    password_hash TEXT         NOT NULL,
    password_salt VARCHAR(64)  NOT NULL DEFAULT '',
    password_algo VARCHAR(16)  NOT NULL DEFAULT 'argon2',
    role          VARCHAR(16)  NOT NULL DEFAULT 'employee',
    display_name  VARCHAR(128) NOT NULL DEFAULT '',
    avatar        VARCHAR(512) NOT NULL DEFAULT '',
    disabled      BOOLEAN      NOT NULL DEFAULT FALSE,
    org_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_qwenpaw_users PRIMARY KEY (tenant_id, username)
);

COMMENT ON TABLE qwenpaw_users IS
'账号主表（M2 权威存储；users.json 保留为无 PG 部署回退�?;
COMMENT ON COLUMN qwenpaw_users.username IS
'用户名（不可变身份锚点：会话/记忆/运行日志按此归属�?;
COMMENT ON COLUMN qwenpaw_users.password_algo IS
'密码散列算法: argon2, sha256（legacy，登录时透明升级�?;
COMMENT ON COLUMN qwenpaw_users.role IS '角色: admin, employee';
COMMENT ON COLUMN qwenpaw_users.org_id IS
'归属组织（租户预留；部门成员关系�?department_members�?;

-- 渠道外部身份 �?账号绑定（wechat:openid 等映射到注册用户名）
CREATE TABLE IF NOT EXISTS user_identity_bindings (
    tenant_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    channel          VARCHAR(32)  NOT NULL,
    external_user_id VARCHAR(128) NOT NULL,
    username         VARCHAR(64)  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_identity_bindings
        PRIMARY KEY (tenant_id, channel, external_user_id)
);

COMMENT ON TABLE user_identity_bindings IS
'渠道外部身份 �?账号绑定（wechat:openid 等映射到注册用户名）';
COMMENT ON COLUMN user_identity_bindings.external_user_id IS
'渠道侧用户标识（openid/userid 等，渠道内唯一�?;

-- 运行日志按发起用户筛�?权限过滤的高频路径（employee 仅看自己�?
CREATE INDEX IF NOT EXISTS ix_agent_runs_user
ON agent_runs (tenant_id, agent_id, user_id, started_at)
WHERE user_id IS NOT NULL;


-- [变更说明] 员工治理表增加后台配置域授权三列（manage_visibility /
--            manage_granted_departments / manage_granted_users）：
--            1) manage_visibility 两级：private-仅创建者可配（默认，最严出厂）/
--               department-部门可配（归属 ∪ 管理授权部门）；不支持 org
--               （"全员可配"用 team_lead 角色表达，避免误配）；
--            2) manage_granted_users 显式授权用户名单（全员可配场景的兜底表达）；
--            3) 治理写入由服务层投影到 RBAC agent_manage_grants（S1 共享配置
--               写端点闸门 require_agent_manage 的运行期消费面）。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0033_employee_governance_manage
--
-- 存量行语义：新增列全部带默认值（private + 空名单），既有治理行自动落
-- 最严语义，仅创建者/admin/team_lead 可配，无越权放开。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_granted_departments JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE employee_governance
    ADD COLUMN IF NOT EXISTS manage_granted_users JSONB NOT NULL DEFAULT '[]'::jsonb;

-- CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_employee_governance_manage_visibility'
    ) THEN
        ALTER TABLE employee_governance ADD CONSTRAINT
        ck_employee_governance_manage_visibility
        CHECK (manage_visibility IN ('private', 'department'));
    END IF;
END
$$;

COMMENT ON COLUMN employee_governance.manage_visibility IS
    '可配置范围（后台配置域授权维）: private-仅创建者可配（默认）, '
    'department-部门可配（归属 ∪ 管理授权部门）；不支持 org，'
    '全员可配用 team_lead 角色（agent:manage）表达';
COMMENT ON COLUMN employee_governance.manage_granted_departments IS
    '管理授权部门 id 数组（manage_visibility=department 时生效，'
    '写入时展开子树投影为 dept:{path} team 集合）';
COMMENT ON COLUMN employee_governance.manage_granted_users IS
    '管理授权用户名单（显式 usernames；与创建者并集恒可配，'
    '覆盖"个别跨部门人员可配"与全员可配的兜底表达）';


-- ============================================================
-- M6 知识中心一期（0034_kb_pg_plane / changelog 20260917/02）：
-- 知识库权威平面六表（kb_spaces/kb_documents/kb_document_versions/
-- kb_chunks/kb_links/agent_kb_bindings）+ pgvector 扩展与索引
-- ============================================================
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_spaces (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'personal',
    owner_id VARCHAR(64) NOT NULL DEFAULT '',
    team_id VARCHAR(64) NOT NULL DEFAULT '',
    grants JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding_model TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT 'auto',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_kb_spaces PRIMARY KEY (tenant_id, id),
    CONSTRAINT ck_kb_spaces_scope CHECK (scope IN ('personal', 'team', 'enterprise')),
    CONSTRAINT ck_kb_spaces_engine CHECK (engine IN ('auto', 'pgvector', 'milvus'))
);

CREATE TABLE IF NOT EXISTS kb_documents (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    content_md TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    source_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingest_status TEXT NOT NULL DEFAULT 'ready',
    error TEXT NOT NULL DEFAULT '',
    is_delete BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_kb_documents PRIMARY KEY (tenant_id, id)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_kb_documents_source'
    ) THEN
        ALTER TABLE kb_documents ADD CONSTRAINT ck_kb_documents_source
        CHECK (source IN ('manual', 'upload', 'url'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_kb_documents_ingest_status'
    ) THEN
        ALTER TABLE kb_documents ADD CONSTRAINT ck_kb_documents_ingest_status
        CHECK (ingest_status IN ('pending', 'processing', 'ready', 'failed'));
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS kb_document_versions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    document_id VARCHAR(64) NOT NULL,
    version INTEGER NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_kb_document_versions PRIMARY KEY (tenant_id, document_id, version)
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    document_id VARCHAR(64) NOT NULL,
    seq INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    parent_chunk_id VARCHAR(64) NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL DEFAULT 0,
    content_text TEXT NOT NULL DEFAULT '',
    tsv tsvector,
    embedding vector(1024),
    model_name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_kb_chunks PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS kb_links (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    src_document_id VARCHAR(64) NOT NULL,
    dst_path TEXT NOT NULL DEFAULT '',
    dst_document_id VARCHAR(64) NOT NULL DEFAULT '',
    context_snippet TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_kb_links PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS agent_kb_bindings (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    space_id VARCHAR(64) NOT NULL,
    granted_by VARCHAR(64) NOT NULL DEFAULT '',
    remark TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_kb_bindings PRIMARY KEY (tenant_id, agent_id, space_id)
);

CREATE INDEX IF NOT EXISTS ix_kb_spaces_scope ON kb_spaces (tenant_id, scope);
CREATE INDEX IF NOT EXISTS ix_kb_documents_space ON kb_documents (tenant_id, space_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_documents_path
    ON kb_documents (tenant_id, space_id, path) WHERE NOT is_delete;
CREATE INDEX IF NOT EXISTS ix_kb_document_versions_doc
    ON kb_document_versions (tenant_id, document_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_space ON kb_chunks (tenant_id, space_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_document ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_tsv ON kb_chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding
    ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_kb_links_src ON kb_links (src_document_id);
CREATE INDEX IF NOT EXISTS ix_kb_links_dst ON kb_links (dst_document_id);
CREATE INDEX IF NOT EXISTS ix_agent_kb_bindings_space
    ON agent_kb_bindings (tenant_id, space_id);

COMMENT ON TABLE kb_spaces IS
    '知识库注册表（知识中心权威平面：库名/描述/scope/grants/引擎路由；'
    'JSON kb_registry.json 的 PG 投影，json 后端零动作、pg 权威读）';
COMMENT ON COLUMN kb_spaces.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN kb_spaces.id IS '知识库 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN kb_spaces.name IS '知识库名称（目录注入展示用）';
COMMENT ON COLUMN kb_spaces.description IS
    '检索场景描述（路由信号：回答数字员工何时该查本库，建库必填）';
COMMENT ON COLUMN kb_spaces.scope IS
    '可见范围: personal-个人私有, team-团队共享, enterprise-企业全员';
COMMENT ON COLUMN kb_spaces.owner_id IS '归属用户（personal scope：库所有者）';
COMMENT ON COLUMN kb_spaces.team_id IS '归属团队（team scope：团队 id）';
COMMENT ON COLUMN kb_spaces.grants IS
    '范围外显式授权 JSONB {roles,users,teams}（与 M4-3 agent/model grant 语义一致）';
COMMENT ON COLUMN kb_spaces.embedding_model IS
    '本库 embedding 模型名（空串=全局默认 text-embedding-v4）';
COMMENT ON COLUMN kb_spaces.engine IS
    '索引引擎路由: auto/pgvector-默认 pgvector 引擎, milvus-大库显式启用 Milvus（按库开关）';
COMMENT ON COLUMN kb_spaces.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN kb_spaces.updated_at IS '更新时间（DB 自动维护，UTC）';

COMMENT ON TABLE kb_documents IS
    '知识文档表（Markdown 权威源：Single Source of Truth，向量索引是其可重建派生缓存）';
COMMENT ON COLUMN kb_documents.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN kb_documents.id IS '文档 ID（业务侧生成）';
COMMENT ON COLUMN kb_documents.space_id IS '所属知识库 id（关联 kb_spaces）';
COMMENT ON COLUMN kb_documents.path IS
    '库内目录路径（如 孕产/用药/甲减.md，前端目录树数据源；可空）';
COMMENT ON COLUMN kb_documents.title IS '文档标题';
COMMENT ON COLUMN kb_documents.content_md IS
    'Markdown 正文全文（权威源，人工可修正，修正即重切重嵌）';
COMMENT ON COLUMN kb_documents.content_hash IS
    '内容 sha256 指纹：与既有行相同则跳过重切重嵌（版本不抖动）';
COMMENT ON COLUMN kb_documents.source IS '来源: manual-页面编辑, upload-文件上传, url-网页抓取';
COMMENT ON COLUMN kb_documents.source_meta IS '来源元数据 JSONB（原始文件名/大小/URL 等）';
COMMENT ON COLUMN kb_documents.ingest_status IS
    '文档级异步摄入状态: pending-待处理, processing-解析中, ready-可检索, failed-失败（error 携带原因）';
COMMENT ON COLUMN kb_documents.error IS '摄入失败原因（failed 时可读；空串=无错误）';
COMMENT ON COLUMN kb_documents.is_delete IS '逻辑删除标记（核心知识数据禁止物理删除）';
COMMENT ON COLUMN kb_documents.updated_by IS '最后更新人（用户账号）';
COMMENT ON COLUMN kb_documents.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN kb_documents.updated_at IS '更新时间（DB 自动维护，UTC）';

COMMENT ON TABLE kb_document_versions IS '文档版本快照（编辑回溯：内容变更时追加一行）';
COMMENT ON COLUMN kb_document_versions.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN kb_document_versions.document_id IS '文档 id（关联 kb_documents）';
COMMENT ON COLUMN kb_document_versions.version IS '版本号（同文档单调递增）';
COMMENT ON COLUMN kb_document_versions.content_md IS '该版本 Markdown 全文快照';
COMMENT ON COLUMN kb_document_versions.content_hash IS '该版本内容指纹';
COMMENT ON COLUMN kb_document_versions.created_by IS '写入人（用户账号）';
COMMENT ON COLUMN kb_document_versions.created_at IS '快照时间（DB 自动维护，UTC）';

COMMENT ON TABLE kb_chunks IS
    '切片派生索引表（可全量重建：pgvector 稠密向量 + tsvector 全文 + 结构锚点）';
COMMENT ON COLUMN kb_chunks.id IS '切片 ID（doc_id_seq 稳定生成）';
COMMENT ON COLUMN kb_chunks.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN kb_chunks.space_id IS '所属知识库 id（S0 ACL 收敛过滤列）';
COMMENT ON COLUMN kb_chunks.document_id IS '所属文档 id（关联 kb_documents）';
COMMENT ON COLUMN kb_chunks.seq IS '切片在文档内的序号（单调递增）';
COMMENT ON COLUMN kb_chunks.heading_path IS
    '标题路径（如 孕产用药 > 甲减 > 妊娠早期），embedding 拼接与 S2 结构扩展依据';
COMMENT ON COLUMN kb_chunks.parent_chunk_id IS
    '父切片 id（长段拆分时回指原语义块；空串=无父块）';
COMMENT ON COLUMN kb_chunks.token_count IS '切片 token 估算数（切片器目标 600）';
COMMENT ON COLUMN kb_chunks.content_text IS '切片正文（不含 heading_path 拼接前缀）';
COMMENT ON COLUMN kb_chunks.tsv IS
    '全文检索向量（应用层分词后以 simple 配置写入：英文词 + CJK bigram）';
COMMENT ON COLUMN kb_chunks.embedding IS
    '稠密向量 1024 维（DashScope text-embedding-v4，HNSW cosine 索引）';
COMMENT ON COLUMN kb_chunks.model_name IS '产生该向量的 embedding 模型名（换模型重建依据）';
COMMENT ON COLUMN kb_chunks.created_at IS '索引写入时间（DB 自动维护，UTC）';

COMMENT ON TABLE kb_links IS
    'wikilink 边表（文档正文 [[路径]] 解析落表；S2 expand=graph 图扩展数据源）';
COMMENT ON COLUMN kb_links.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN kb_links.id IS '链接边 ID（业务侧生成，与 tenant_id 组成联合主键）';
COMMENT ON COLUMN kb_links.space_id IS '所属知识库 id';
COMMENT ON COLUMN kb_links.src_document_id IS '链接源文档 id';
COMMENT ON COLUMN kb_links.dst_path IS '链接目标路径（[[路径]] 原文）';
COMMENT ON COLUMN kb_links.dst_document_id IS '解析到的目标文档 id（悬挂链接为空串）';
COMMENT ON COLUMN kb_links.context_snippet IS '链接所在句子上下文（图扩展摘要展示用）';
COMMENT ON COLUMN kb_links.created_at IS '解析落表时间（DB 自动维护，UTC）';

COMMENT ON TABLE agent_kb_bindings IS
    '数字员工↔知识库授权绑定表（绑定即授权，决策点 1：Agent 检索可见性=其绑定库集合）';
COMMENT ON COLUMN agent_kb_bindings.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN agent_kb_bindings.agent_id IS '数字员工 id';
COMMENT ON COLUMN agent_kb_bindings.space_id IS
    '知识库 id（写入前经 can_manage_space 管理权校验）';
COMMENT ON COLUMN agent_kb_bindings.granted_by IS '授权人（用户账号）';
COMMENT ON COLUMN agent_kb_bindings.remark IS '备注（授权说明）';
COMMENT ON COLUMN agent_kb_bindings.created_at IS '绑定时间（DB 自动维护，UTC）';


-- [变更说明] 定时任务表增加个人任务归属三列（owner_user_id /
--            department_id / project_id），落地双平面模型的 S2 用户个人平面：
--            1) owner_user_id 非空=个人任务（仅 owner 本人 + 平台管理员可见可改，
--               跨人严格隔离）；为空=员工共享任务（S1，使用授权内全员可见、
--               员工级管理授权者可写）；
--            2) department_id 为 owner 部门归属快照（写入时经 org 目录解析的部门
--               path，ops 按部门检索/归属统计用）；project_id 为预留列（个人定时
--               任务暂无项目维度，恒空）；
--            3) 三列均为 spec JSONB 内 CronJobSpec 同名字段的可查询投影——权威仍在
--               spec（随 json/pg 两平面往返），投影列仅供运维按 owner/部门检索。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0035_cron_jobs_owner
--
-- 存量行语义：owner_user_id 默认 NULL → 自动落"员工共享"语义，与既有全员可见
-- 行为一致，无越权收紧。全部 DDL 幂等（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS department_id TEXT;
ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS project_id TEXT;

-- 归属检索索引（tenant + agent + owner）：list 过滤共享/个人与 ops 归属统计走此
CREATE INDEX IF NOT EXISTS ix_cron_jobs_owner
    ON cron_jobs (tenant_id, agent_id, owner_user_id);

COMMENT ON COLUMN cron_jobs.owner_user_id IS
    '个人任务归属用户（spec.owner_user_id 的可查询投影）: 非空=个人任务'
    '（仅 owner+平台管理员可见可改，跨人隔离）, 空=员工共享任务'
    '（使用授权内全员可见、员工级管理授权者可写）';
COMMENT ON COLUMN cron_jobs.department_id IS
    'owner 部门归属快照（写入时经 org 目录解析的部门 path；无 PG 或'
    'owner 无部门时为空；ops 按部门检索/归属统计用）';
COMMENT ON COLUMN cron_jobs.project_id IS
    'owner 项目归属快照（预留列；个人定时任务暂无项目维度，恒空）';


-- [变更说明] 新增个人技能包权威表 agent_skill_bundles（S2 用户个人平面）：
--            1) 承载用户个人技能的完整文件树（files JSONB path→content 扁平映射），
--               owner_user_id 非空即个人技能，仅 owner 本人 + 平台管理员可见可改
--               （跨人严格隔离）；
--            2) 与员工共享技能刻意分表——共享技能维持既有「技能池 + workspace
--               skill.json 文件链」平面（skill_catalog / agent_skill_bindings /
--               skill_content_snapshots），本表不承载共享技能，避免三平面语义分叉；
--            3) 运行时物化到 workspace/.personal_skills/{user}/{skill}/ 参与并集
--               扫描（不进共享 manifest）；department_id/project_id 为 owner 归属
--               快照（ops 检索/归属统计用）；
--            4) QWENPAW_STORAGE_BACKEND=json（默认）时本表零动作，dual/pg 时权威。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0036_agent_skill_bundles

-- 建表幂等：CREATE TABLE IF NOT EXISTS，存量库重复执行不报错
CREATE TABLE IF NOT EXISTS agent_skill_bundles (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    owner_user_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    files JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    department_id TEXT,
    project_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_skill_bundles
        PRIMARY KEY (tenant_id, agent_id, owner_user_id, name)
);

-- 归属检索索引（tenant + agent + owner）：个人技能列表按 owner 拉取走此
CREATE INDEX IF NOT EXISTS ix_agent_skill_bundles_owner
    ON agent_skill_bundles (tenant_id, agent_id, owner_user_id);

COMMENT ON TABLE agent_skill_bundles IS
    '个人技能包权威表（S2 用户个人平面：user×agent 私有技能的完整文件树；'
    '与共享技能池/绑定平面刻意分表，仅承载个人技能，避免三平面语义分叉。'
    'json 后端零动作、dual/pg 权威；运行时物化到 .personal_skills 参与并集扫描）';
COMMENT ON COLUMN agent_skill_bundles.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN agent_skill_bundles.agent_id IS '数字员工 ID（workspace 目录名，与 agent_skill_bindings 同约定）';
COMMENT ON COLUMN agent_skill_bundles.owner_user_id IS '个人技能归属用户（非空即个人技能；仅 owner+平台管理员可见可改，跨人隔离）';
COMMENT ON COLUMN agent_skill_bundles.name IS '技能名（规范化目录名；同 owner+agent 内唯一，与共享技能名空间独立）';
COMMENT ON COLUMN agent_skill_bundles.files IS '技能目录全树 JSONB（path→content 扁平映射，含 SKILL.md/references/scripts；物化到 .personal_skills/{user}/{skill}/ 的权威源）';
COMMENT ON COLUMN agent_skill_bundles.enabled IS '是否启用（禁用后不物化、不注入该用户运行时）';
COMMENT ON COLUMN agent_skill_bundles.version IS '内容版本号（同技能单调递增，乐观并发/变更追溯用）';
COMMENT ON COLUMN agent_skill_bundles.department_id IS 'owner 部门归属快照（写入时经 org 目录解析的部门 path；无 PG 或 owner 无部门时为空；ops 按部门检索/归属统计用）';
COMMENT ON COLUMN agent_skill_bundles.project_id IS 'owner 项目归属快照（预留列；个人技能暂无项目维度，恒空）';
COMMENT ON COLUMN agent_skill_bundles.created_at IS '创建时间（首次写入时生成）';
COMMENT ON COLUMN agent_skill_bundles.updated_at IS '更新时间（每次内容变更时刷新）';


-- [变更说明] SOP 表增加归属快照两列（department_id / project_id），补齐
--            S2 个人资产的业务域归属（SOP 私有能力化后 owner_id = 归属员工 id）：
--            1) department_id 为 owner 部门归属快照（写入时经 org 目录解析的部门
--               path：员工 owner 取其治理行归属部门，用户名 owner 按部门成员解析；
--               无 PG 或 owner 无部门时为空）；行诞生即快照，随 promote/fork/
--               rollback 复制，不随重复发布抖动；
--            2) project_id 为预留列（SOP 暂无项目维度，恒空）；
--            3) 两列为普通可查询投影（非 JSONB 内字段），ops 按部门检索/归属统计
--               用；存量行 NULL 无越权语义变化（可见性仍由 environment + owner_id
--               决定：“个人 draft 仅 owner、production 全员”）。
-- [变更时间] 2026-09-17
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0037_sops_owner_attributes
--
-- 全部 DDL 幂等（ADD COLUMN / CREATE INDEX IF NOT EXISTS）。

-- 加列幂等：ADD COLUMN IF NOT EXISTS，存量库重复执行不报错
ALTER TABLE sops ADD COLUMN IF NOT EXISTS department_id TEXT;
ALTER TABLE sops ADD COLUMN IF NOT EXISTS project_id TEXT;

-- 归属检索索引（tenant + department）：ops 按部门检索/归属统计走此
CREATE INDEX IF NOT EXISTS ix_sops_department
    ON sops (tenant_id, department_id);

COMMENT ON COLUMN sops.department_id IS
    'owner 部门归属快照（写入时经 org 目录解析的部门 path；员工 owner '
    '取治理行归属部门，用户名 owner 按部门成员解析；无 PG 或 owner 无'
    '部门时为空；ops 按部门检索/归属统计用）';
COMMENT ON COLUMN sops.project_id IS
    'owner 项目归属快照（预留列；SOP 暂无项目维度，恒空）';

-- [变更说明] agent_documents 增加 owner_user_id 个人草稿维（T11 个人档案草稿）：
--            1) 加列 owner_user_id（NULL=员工共享行；非空=该用户的个人草稿行，
--               与正式 agent_id 的 environment=draft 组合承载「员工写四文档
--               落本人 draft 行（不触共享行）」）；
--            2) 唯一约束重建：旧约束 uq_agent_documents_doc
--               (tenant,agent,doc_type,environment) 删除，改为表达式唯一索引
--               （owner NULL 归一为空串）——允许同一文档下多用户各持一份
--               个人草稿，同时保持共享行唯一；
--            3) 存量行 owner_user_id 为 NULL，语义不变（共享行）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0038_agent_documents_owner_draft
--
-- 全部 DDL 幂等（ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS /
-- CREATE UNIQUE INDEX IF NOT EXISTS）。

ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64);

ALTER TABLE agent_documents DROP CONSTRAINT IF EXISTS uq_agent_documents_doc;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_documents_doc_owner
    ON agent_documents (tenant_id, agent_id, doc_type, environment,
                        COALESCE(owner_user_id, ''));

COMMENT ON COLUMN agent_documents.owner_user_id IS
    '个人草稿 owner（NULL=员工共享行；非空=该用户的个人草稿行，与 environment=draft 组合；管理员应用 apply 后 promote 到共享行）';


-- ==== T12 driver_cards / driver_credentials (changelog 20260918/02) ====
-- [变更说明] 新增 MCP/ACP 驱动卡 PG 权威双表（T12 driver PG 权威）：
--            1) driver_cards：数字员工外部能力驱动卡（MCP/ACP）权威表，
--               自然键 (tenant, agent, protocol, name)；enabled 独立列，
--               spec JSONB 承载 endpoint/config/credentials(alias→{kind,ref})，
--               policy JSONB 承载 DriverPolicy（默认效应 + 规则数组）；
--            2) driver_credentials：驱动凭据密文表，自然键
--               (tenant, agent, ref)；cipher 存放经 secret_store（Fernet）
--               加密后的凭据 JSON（kind/public/secrets/meta），明文不落库。
--            json 后端（无 PG）两表零动作，驱动卡仍走 workspace 文件平面；
--            pg/dual 后端以本两表为权威源，文件降级为投影（写穿 + 启动回填）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0039_driver_cards_credentials
--
-- 全部 DDL 幂等（CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS）。

CREATE TABLE IF NOT EXISTS driver_cards (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    protocol VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    spec JSONB NOT NULL DEFAULT '{}',
    policy JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_cards
        PRIMARY KEY (tenant_id, agent_id, protocol, name)
);

CREATE INDEX IF NOT EXISTS ix_driver_cards_agent
    ON driver_cards (tenant_id, agent_id);

CREATE TABLE IF NOT EXISTS driver_credentials (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    cipher TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_driver_credentials
        PRIMARY KEY (tenant_id, agent_id, ref)
);

CREATE INDEX IF NOT EXISTS ix_driver_credentials_agent
    ON driver_credentials (tenant_id, agent_id);

COMMENT ON TABLE driver_cards IS
    'MCP/ACP 驱动卡权威表（数字员工外部能力配置：endpoint/config/凭据引用/访问策略；json 后端零动作、pg/dual 权威，文件降级为写穿投影 + 启动回填）';
COMMENT ON COLUMN driver_cards.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN driver_cards.agent_id IS '数字员工 ID（workspace 目录名，与 agent_documents 同约定）';
COMMENT ON COLUMN driver_cards.protocol IS '驱动协议（如 mcp/acp，与文件投影目录 drivers/{protocol}/{name}.yaml 对齐）';
COMMENT ON COLUMN driver_cards.name IS '驱动卡名（同 agent+protocol 内唯一，运行时全局唯一）';
COMMENT ON COLUMN driver_cards.enabled IS '是否启用（禁用后运行时不构建该 driver）';
COMMENT ON COLUMN driver_cards.spec IS '驱动卡主体 JSONB（endpoint/config/credentials：alias→{kind,ref}；凭据密文另存 driver_credentials）';
COMMENT ON COLUMN driver_cards.policy IS '访问策略 JSONB（DriverPolicy：default_effect + rules 数组）';
COMMENT ON COLUMN driver_cards.created_at IS '创建时间（首次写入时生成）';
COMMENT ON COLUMN driver_cards.updated_at IS '更新时间（每次内容变更时刷新）';

COMMENT ON TABLE driver_credentials IS
    '驱动凭据密文表（secret_store/Fernet 加密后的凭据 JSON：kind/public/secrets/meta；明文绝不落库，cipher 为空表示无密文）';
COMMENT ON COLUMN driver_credentials.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN driver_credentials.agent_id IS '数字员工 ID（workspace 目录名）';
COMMENT ON COLUMN driver_credentials.ref IS '凭据引用（与 DriverCard.credentials 的 ref 对应，env: 前缀引用不落库）';
COMMENT ON COLUMN driver_credentials.cipher IS '凭据密文（secret_store.encrypt 后的 JSON，带 ENC: 前缀；读取时 decrypt 还原）';
COMMENT ON COLUMN driver_credentials.created_at IS '创建时间（首次写入时生成）';
COMMENT ON COLUMN driver_credentials.updated_at IS '更新时间（每次内容变更时刷新）';

-- [变更说明] cron 双台账收口 Phase 1（T13a EXPAND，设计文档 docs/design/
--            2026-09-18-cron-ledger-convergence.md）：expert 两表
--            （expert_scheduled_tasks/expert_task_runs）收口进 cron 双表前，
--            先补齐权威面缺失的执行留痕与统计字段——
--            1) cron_job_history 补 4 列：result_summary（执行结果摘要，
--               worklog 时间线标题来源）、run_id/session_id（关联 agent_runs
--               运行详情与会话回放的跳转键；模型早有且 manager 已赋值，
--               pg_repo INSERT 此前丢列，本次补齐落库面）、scheduled_for
--               （调度槽位时间：trigger=scheduled 时取 run_at，手动为空）；
--            2) cron_jobs 补 run_count：历史累计执行次数冗余计数
--               （append_history 同事务 +1；history 仅留最近 50 条，
--               COUNT 反推会被修剪窗截断——决策 D3）。
--            全部新列带默认值，写路径补列对老代码零影响；读路径切换
--            在 Phase 2（回填+委托），DROP expert 两表在 Phase 3。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0040_cron_ledger_expand
--
-- 全部 DDL 幂等（ADD COLUMN IF NOT EXISTS）。

ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS result_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS run_id VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS session_id TEXT NOT NULL DEFAULT '';
ALTER TABLE cron_job_history ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

ALTER TABLE cron_jobs ADD COLUMN IF NOT EXISTS run_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN cron_job_history.result_summary IS '执行结果摘要（final_text 截断 500 字，worklog 时间线标题来源）';
COMMENT ON COLUMN cron_job_history.run_id IS '关联 agent_runs 的运行 ID（执行详情跳转键；text 任务为空）';
COMMENT ON COLUMN cron_job_history.session_id IS '本次执行落库的会话 ID（share_session=False 时为 cron:{job_id}，会话回放跳转键）';
COMMENT ON COLUMN cron_job_history.scheduled_for IS '调度槽位时间（trigger=scheduled 时等于 run_at，手动触发为空）';
COMMENT ON COLUMN cron_jobs.run_count IS '历史累计执行次数（append_history 同事务 +1；history 仅留最近 50 条，精确计数不能靠 COUNT 反推）';

-- [变更说明] cron 双台账收口 Phase 3（T13d CONTRACT，设计文档 docs/design/
--            2026-09-18-cron-ledger-convergence.md §4.4）：expert 两表全部读
--            字段已由 0040 补入 cron 双表、写路径已改基 CronManager 权威 +
--            CronLedgerReader 读回（scheduling.py / expert_capability.py 停写），
--            两张 legacy 台账表退役 DROP——
--            1) expert_task_runs：执行留痕已落 cron_job_history；
--            2) expert_scheduled_tasks：规格投影已落 cron_jobs + spec.meta。
--            前置（运维步骤，本文件不含）：DROP 前 pg_dump 备份两表；先停写
--            观察业务无异常再 DROP（expand-contract 分变更日原则）。
-- [变更时间] 2026-09-18
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0041_drop_expert_ledger
--
-- DROP TABLE IF EXISTS 幂等；DROP 顺序先 runs 后 tasks（子表语义）。
-- 回滚：alembic downgrade 0041 内置完整重建 DDL（0012 建表 + 0029 加列/
--       索引/约束），但重建为空表，历史数据须从 DROP 前 pg_dump 备份恢复。

DROP TABLE IF EXISTS expert_task_runs;
DROP TABLE IF EXISTS expert_scheduled_tasks;

-- [变更说明] 企业级 RBAC 组织权限升级 - qwenpaw_users 补员工档案字段
-- [变更时间] 2026-09-19  [变更人] 清风  [等价 alembic] 0043_employee_profile
-- 部门员工管理所需的姓名/手机号/性别/职位/超管标记；ADD COLUMN IF NOT
-- EXISTS 幂等，登录身份锚点仍为 username。
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS real_name     VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS phone         VARCHAR(32)  NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS gender        SMALLINT     NOT NULL DEFAULT 0;
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS position      VARCHAR(64)  NOT NULL DEFAULT '';
ALTER TABLE qwenpaw_users ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN      NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN qwenpaw_users.real_name IS '员工姓名（部门员工列表主展示列，区别于登录显示名 display_name）';
COMMENT ON COLUMN qwenpaw_users.phone IS '手机号（部门员工列表关键字搜索命中列）';
COMMENT ON COLUMN qwenpaw_users.gender IS '性别: 0-未知, 1-男, 2-女（前端转描述文本展示）';
COMMENT ON COLUMN qwenpaw_users.position IS '职位';
COMMENT ON COLUMN qwenpaw_users.is_superadmin IS '超管标记: TRUE 时禁止被禁用/删除/降级，默认超级管理员账号置此标记';
CREATE INDEX IF NOT EXISTS ix_qwenpaw_users_tenant_disabled ON qwenpaw_users (tenant_id, disabled);
