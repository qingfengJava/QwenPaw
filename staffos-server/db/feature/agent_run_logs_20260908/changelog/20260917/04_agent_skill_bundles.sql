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
