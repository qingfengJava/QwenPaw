-- ============================================================
-- 变更说明: 专家目录平面扩展 —— experts 四表升级为「专家市场」
--           1) experts 新增 10 列：owner_id（自定义专家归属，
--              NULL=管理员/内置，未来权限分配锚点）/ visibility
--              （org=全员可见 | private=仅自己，预留 department/
--              shared）/ is_builtin（内置专家标记）/ title（职称）/
--              category（分类 slug，市场页 tab）/ badge（特邀徽章）/
--              tags（标签数组）/ system_prompt（领域人设，发布时
--              物化进 workspace PROFILE.md）/ usage_count（召唤计数，
--              "最热"排序）/ featured（精选场景标记）+ 2 个索引
--              （市场复合索引 / 归属索引）
--           2) 新表 expert_skills：专家-技能绑定关系（skill_name 引用
--              共享技能注册表，registry 为权威；enabled 支持停用不丢
--              绑定；seq 维持注入顺序）。技能永不写入 agent_spec ——
--              AgentProfileConfig 无 skills 字段会静默丢弃；发布时物化
--              进专家 workspace skills/ 目录实现会话自动加载
--           3) expert_teams 新增 4 列：owner_id / category / tags /
--              orchestration（JSONB，运行时编排器预留：并行组/DAG/
--              成员任务模板）
--           4) expert_team_members 新增 member_role（lead=主理人 /
--              member），专家团详情页主理人徽标
-- 变更时间: 2026-08-18
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0009_expert_catalog（Revises 0008_xian_shares）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. experts 扩展列（全部可空或有默认值，存量行语义不变：
--    owner_id NULL + visibility 'org' + is_builtin FALSE 即与管理员
--    创建的现有专家完全一致）
-- ------------------------------------------------------------

ALTER TABLE experts ADD COLUMN IF NOT EXISTS owner_id TEXT;
ALTER TABLE experts ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'org';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS is_builtin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE experts ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS badge TEXT NOT NULL DEFAULT '';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS system_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS usage_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE experts ADD COLUMN IF NOT EXISTS featured BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN experts.owner_id IS '归属账号（自定义专家=创建者 username；NULL=管理员创建或内置专家；未来权限分配的锚点）';
COMMENT ON COLUMN experts.visibility IS '可见范围：org=全员可见（叠加 RBAC grants）；private=仅 owner 可见；department/shared 为未来权限版本预留';
COMMENT ON COLUMN experts.is_builtin IS '是否内置专家（随包 seed，固定 id builtin_*，幂等 upsert；不可被用户删除）';
COMMENT ON COLUMN experts.title IS '职称（市场卡片副标题，如"高级开发工程师"）';
COMMENT ON COLUMN experts.category IS '分类 slug（市场页分类 tab；字典见 EXPERT_CATEGORIES：general/research/writing/dev/data/business/office）';
COMMENT ON COLUMN experts.badge IS '徽章文案（如"特邀专家"，空串=无徽章）';
COMMENT ON COLUMN experts.tags IS '标签数组（JSONB 字符串数组，市场卡片能力标签行）';
COMMENT ON COLUMN experts.system_prompt IS '领域人设提示词（发布时渲染进专家 workspace PROFILE.md，承载 ReAct 工作法与角色设定）';
COMMENT ON COLUMN experts.usage_count IS '召唤计数（前端点击"召唤专家"时原子 +1，驱动"最热"排序；精确 token 计量走 token_usage_events 的 agent_id 维度）';
COMMENT ON COLUMN experts.featured IS '是否精选（市场页精选场景区标记）';

-- ------------------------------------------------------------
-- 2. expert_teams / expert_team_members 扩展列（结构预留）
-- ------------------------------------------------------------

ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS owner_id TEXT;
ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general';
ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]';
ALTER TABLE expert_teams ADD COLUMN IF NOT EXISTS orchestration JSONB NOT NULL DEFAULT '{}';
ALTER TABLE expert_team_members ADD COLUMN IF NOT EXISTS member_role TEXT NOT NULL DEFAULT 'member';

COMMENT ON COLUMN expert_teams.owner_id IS '归属账号（NULL=管理员创建）';
COMMENT ON COLUMN expert_teams.category IS '分类 slug（与 experts.category 字典一致）';
COMMENT ON COLUMN expert_teams.tags IS '标签数组（JSONB 字符串数组）';
COMMENT ON COLUMN expert_teams.orchestration IS '运行时编排预留（JSONB：并行组/DAG/成员任务模板；由未来 RuntimeTeamOrchestrator 读取，当前发布链不消费）';
COMMENT ON COLUMN expert_team_members.member_role IS '成员角色：lead=主理人（详情页徽标）/ member=普通成员';

-- ------------------------------------------------------------
-- 3. 新表 expert_skills（专家-技能绑定，registry 为权威）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS expert_skills (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    expert_id  VARCHAR(64) NOT NULL,
    skill_name TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    seq        INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_skills PRIMARY KEY (tenant_id, expert_id, skill_name)
);

COMMENT ON TABLE expert_skills IS '专家技能绑定表（skill_name 引用共享技能注册表，注册表为权威；发布时 enabled 集合物化进专家 workspace skills/ 目录，运行时 Toolkit 渐进加载实现"使用专家自动加载技能"）';
COMMENT ON COLUMN expert_skills.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN expert_skills.expert_id IS '专家 ID（弱引用 experts.id；专家删除时级联清理由应用层负责）';
COMMENT ON COLUMN expert_skills.skill_name IS '技能名（共享技能注册表内的目录名；注册表改名/卸载后此列为悬空引用，详情接口实时校验）';
COMMENT ON COLUMN expert_skills.enabled IS '是否启用（停用保留绑定不注入；发布时仅物化 enabled=TRUE 的技能）';
COMMENT ON COLUMN expert_skills.seq IS '展示/注入顺序（小值在前）';
COMMENT ON COLUMN expert_skills.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN expert_skills.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 4. 查询索引（市场复合 / 归属 / 绑定）
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_experts_market
    ON experts (tenant_id, status, category, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_experts_owner
    ON experts (tenant_id, owner_id);

CREATE INDEX IF NOT EXISTS ix_expert_skills_expert
    ON expert_skills (tenant_id, expert_id);

-- ------------------------------------------------------------
-- 5. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0009_expert_catalog';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0009_expert_catalog');
    END IF;
END $$;

COMMIT;
