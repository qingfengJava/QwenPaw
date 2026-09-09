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
