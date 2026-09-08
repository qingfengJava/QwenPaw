-- [变更说明] 为缺失备注的 29 张表补充 COMMENT ON TABLE 表级备注
-- [变更时间] 2026-09-08
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/upstream_port_20260903/test.sql] 是
-- [同步至 db/feature/upstream_port_20260903/prod.sql] 是

COMMENT ON TABLE orgs IS '企业组织表：租户边界，一条记录代表一个企业组织';
COMMENT ON TABLE departments IS '部门表：组织内部门，通过 parent_id 构成树形结构';
COMMENT ON TABLE department_members IS '部门成员关联表：用户与部门的从属关系';
COMMENT ON TABLE projects IS '项目协作表：组织成员共享的协作项目';
COMMENT ON TABLE project_members IS '项目成员表：用户在项目中的成员关系与角色';
COMMENT ON TABLE project_bindings IS '项目资源绑定表：外部资源（连接器/技能）与项目的绑定关系';
COMMENT ON TABLE project_automations IS '项目自动化规则表：项目内定时执行的自动化配置';
COMMENT ON TABLE tasks IS '看板任务表：项目内的看板任务';
COMMENT ON TABLE feed_events IS '项目动态事件表：项目 Feed 的追加写（append-only）活动记录';
COMMENT ON TABLE experts IS '数字员工（专家）主表：可发布管理的 agent 定义';
COMMENT ON TABLE expert_teams IS '专家团队表：轻量多智能体编排单元（含运营位展示字段）';
COMMENT ON TABLE expert_team_members IS '专家团队成员表：专家在团队中的有序成员关系';
COMMENT ON TABLE expert_skills IS '专家技能绑定表：共享技能注册表中的技能与专家的绑定关系';
COMMENT ON TABLE published_experts IS '专家发布快照表：某一专家版本的不可变发布快照';
COMMENT ON TABLE expert_resource_bindings IS '专家资源绑定表：SOP/知识库/工具等能力资源的挂载枢纽';
COMMENT ON TABLE sops IS 'SOP 流程资产表：版本化过程资产，注入 workforce 规划与校验';
COMMENT ON TABLE sop_versions IS 'SOP 版本表：SOP 流程资产的版本历史记录';
COMMENT ON TABLE expert_memories IS '专家长期记忆表：按 profile/preference/fact 分桶，去重键幂等写入';
COMMENT ON TABLE expert_scheduled_tasks IS '专家定时任务投影表：调度权威在 CronManager（job id 前缀 expert_task_）';
COMMENT ON TABLE expert_task_runs IS '专家任务执行记录表：定时任务的每次执行明细';
COMMENT ON TABLE message_feedback IS '消息反馈表：逐条消息的点赞/点踩收集';
COMMENT ON TABLE evolution_proposals IS '进化提案表：反馈驱动的变更提案及人工审核生命周期';
COMMENT ON TABLE expert_api_keys IS '专家开放 API 密钥表：签发/吊销台账（仅持久化 SHA-256 哈希与展示前缀，明文只下发一次）';
COMMENT ON TABLE token_usage_events IS 'Token 用量事件表：按企业维度计量的 LLM Token 用量记录';
COMMENT ON TABLE chats IS '会话主表：会话规格（镜像 ChatSpec / chats.json），按 tenant_id 隔离';
COMMENT ON TABLE session_states IS '会话状态表：会话状态文档（镜像 *.json 会话文件）';
COMMENT ON TABLE history_entries IS '会话历史表：持久化的会话历史事件（镜像 scroll conversation_history）';
COMMENT ON TABLE media_files IS '媒体文件表：聊天媒体文件元数据（字节内容持久化在 PostgreSQL）';
COMMENT ON TABLE alembic_version IS 'Alembic 迁移版本表：记录数据库当前 schema 版本号（框架维护，请勿手工修改）';
