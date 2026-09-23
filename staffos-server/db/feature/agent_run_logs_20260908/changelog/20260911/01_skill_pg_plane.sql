-- [变更说明] 技能系统 PG 落库平面：新增 skill_catalog（技能池目录）+ agent_skill_bindings（员工技能绑定）+ skill_content_snapshots（技能体内容快照）
-- [变更时间] 2026-09-11
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [说明]     技能是数据资产，PG 为唯一权威源：目录/绑定/中文映射/内容快照全落库，
--            文件目录降级为可从快照重建的运行时物化缓存（换服务器恢复 PG 即完整恢复）。
--            json（默认）后端零动作，dual 影子写（manifest primary），pg 权威读（manifest 兜底）。
--            引用化装配：员工装配技能只写绑定行（零文件拷贝），运行时解析优先级
--            私有自建 → 池 → 内置。alembic 等价路径：0023/0024/0025。

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
