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

COMMENT ON COLUMN sops.created_at IS '创建时间（DB 自动维护，UTC）';

COMMENT ON COLUMN sops.updated_at IS '更新时间（DB 自动维护，UTC）';

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
