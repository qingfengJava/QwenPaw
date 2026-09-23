-- ============================================================
-- 变更说明: 知识本体平台 T4 —— Ontology 数据面：
--           1) ontology_types：L0 九类元模型 + L1 十三类业务核心
--              类型种子（幂等 ON CONFLICT DO NOTHING，L2+ 预留）；
--           2) ontology_objects 对象实例（is_delete 逻辑删除）；
--           3) ontology_relations 有向关系边（时效内建）；
--           4) ontology_state_transitions / ontology_rules /
--              ontology_actions 仅建模留档（运行时为后续里程碑）；
--           5) kb_object_links 知识 ↔ 本体互引；
--           6) 七索引（objects(type)/(org,dept)、relations(from/to/
--              type)、links(document/object)）。
--           方案文档字段 trigger 因 PG 保留字更名 trigger_type。
-- 变更时间: 2026-09-20
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0047_kb_ontology（Revises 0046_kb_wiki）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- ============================================================

CREATE TABLE IF NOT EXISTS ontology_types (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    layer VARCHAR(8) NOT NULL DEFAULT 'L1',
    parent_id VARCHAR(64) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    attributes_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS ontology_objects (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    type_id VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    state VARCHAR(64) NOT NULL DEFAULT '',
    state_detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner_id VARCHAR(64) NOT NULL DEFAULT '',
    org_id VARCHAR(64) NOT NULL DEFAULT '',
    department_id VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_delete BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS ontology_relations (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    type VARCHAR(64) NOT NULL,
    from_type VARCHAR(64) NOT NULL,
    from_id VARCHAR(64) NOT NULL,
    to_type VARCHAR(64) NOT NULL,
    to_id VARCHAR(64) NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    confidence REAL NOT NULL DEFAULT 1.0,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS ontology_state_transitions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    object_id VARCHAR(64) NOT NULL,
    from_state VARCHAR(64) NOT NULL DEFAULT '',
    to_state VARCHAR(64) NOT NULL DEFAULT '',
    trigger_type VARCHAR(64) NOT NULL DEFAULT '',
    preconditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    permission VARCHAR(128) NOT NULL DEFAULT '',
    postconditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS ontology_rules (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    scope VARCHAR(64) NOT NULL DEFAULT '',
    object_type VARCHAR(64) NOT NULL DEFAULT '',
    priority INT NOT NULL DEFAULT 3,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    then_actions JSONB NOT NULL DEFAULT '{}'::jsonb,
    else_actions JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from TIMESTAMPTZ,
    version INT NOT NULL DEFAULT 1,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS ontology_actions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    object_type VARCHAR(64) NOT NULL DEFAULT '',
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    preconditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution JSONB NOT NULL DEFAULT '{}'::jsonb,
    postconditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback JSONB NOT NULL DEFAULT '{}'::jsonb,
    auditable BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS kb_object_links (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id VARCHAR(64) NOT NULL,
    kb_space_id VARCHAR(64) NOT NULL,
    kb_document_id VARCHAR(64) NOT NULL,
    object_type VARCHAR(64) NOT NULL,
    object_id VARCHAR(64) NOT NULL,
    relation VARCHAR(48) NOT NULL DEFAULT 'knowledge_mentions',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE INDEX IF NOT EXISTS ix_ontology_objects_type
    ON ontology_objects (tenant_id, type_id);

CREATE INDEX IF NOT EXISTS ix_ontology_objects_org
    ON ontology_objects (tenant_id, org_id, department_id);

CREATE INDEX IF NOT EXISTS ix_ontology_relations_from
    ON ontology_relations (tenant_id, from_id);

CREATE INDEX IF NOT EXISTS ix_ontology_relations_to
    ON ontology_relations (tenant_id, to_id);

CREATE INDEX IF NOT EXISTS ix_ontology_relations_type
    ON ontology_relations (tenant_id, type);

CREATE INDEX IF NOT EXISTS ix_kb_object_links_document
    ON kb_object_links (tenant_id, kb_document_id);

CREATE INDEX IF NOT EXISTS ix_kb_object_links_object
    ON kb_object_links (tenant_id, object_id);

-- L0 九类元模型 + L1 十三类业务核心类型种子
-- （与 qwenpaw.app.ontology.models.SEED_TYPES 字面一致）
INSERT INTO ontology_types
    (tenant_id, id, name, layer, parent_id, description)
VALUES
    ('default', 'l0.object', '对象', 'L0', '',
     '一切实体的元类型；L1 业务实体类型的父层'),
    ('default', 'l0.relation', '关系', 'L0', '', '对象间有向关系的元类型'),
    ('default', 'l0.state', '状态', 'L0', '', '对象生命周期阶段的元类型'),
    ('default', 'l0.transition', '状态迁移', 'L0', '',
     '状态间受控流转的元类型'),
    ('default', 'l0.rule', '规则', 'L0', '',
     '业务约束与自动行为的元类型（本期仅建模）'),
    ('default', 'l0.action', '动作', 'L0', '',
     '可执行操作的元类型（本期仅建模）'),
    ('default', 'l0.event', '事件', 'L0', '', '状态迁移触发器的分类元类型'),
    ('default', 'l0.knowledge', '知识', 'L0', '',
     'LLM Wiki 层已审知识节点的元类型'),
    ('default', 'l0.evidence', '证据', 'L0', '',
     'RAG 层原始证据材料（文档/切片）的元类型'),
    ('default', 'l1.person', '人员', 'L1', 'l0.object',
     '员工/联系人等自然人对象'),
    ('default', 'l1.org', '组织', 'L1', 'l0.object',
     '公司/法人主体（org 即租户边界）'),
    ('default', 'l1.department', '部门', 'L1', 'l0.object',
     '组织内部门（物化路径层级）'),
    ('default', 'l1.team', '团队', 'L1', 'l0.object',
     '跨部门协作团队/专家组'),
    ('default', 'l1.role', '角色', 'L1', 'l0.object', '岗位/职能角色'),
    ('default', 'l1.customer', '客户', 'L1', 'l0.object', '外部客户主体'),
    ('default', 'l1.supplier', '供应商', 'L1', 'l0.object',
     '外部供应商主体'),
    ('default', 'l1.product', '产品', 'L1', 'l0.object', '产品/服务线'),
    ('default', 'l1.contract', '合同', 'L1', 'l0.object', '合同/协议对象'),
    ('default', 'l1.project', '项目', 'L1', 'l0.object', '项目/工程对象'),
    ('default', 'l1.task', '任务', 'L1', 'l0.object', '任务/工单对象'),
    ('default', 'l1.document', '文档', 'L1', 'l0.evidence',
     '知识库文档（kb_documents 互引侧）'),
    ('default', 'l1.knowledge', '知识', 'L1', 'l0.knowledge',
     '已审知识节点（知识层挂接点）')
ON CONFLICT (tenant_id, id) DO NOTHING;

COMMENT ON TABLE ontology_types IS
    '本体类型（L0 元模型 + L1 业务核心种子；L2+ 企业自定义分层预留）';

COMMENT ON TABLE ontology_objects IS
    '本体对象实例（state 为业务状态机标签；迁移历史见 '
    'ontology_state_transitions）';

COMMENT ON TABLE ontology_relations IS
    '本体有向关系边（valid_from/valid_to 表达关系时效）';

COMMENT ON TABLE ontology_state_transitions IS
    '状态迁移留档（trigger 字段因 PG 保留字更名 trigger_type；'
    '仅建模无运行时）';

COMMENT ON TABLE ontology_rules IS
    '业务规则留档（条件 DSL 评估引擎为后续里程碑）';

COMMENT ON TABLE ontology_actions IS
    '动作定义留档（执行/审批链为后续里程碑，复用 app/approvals）';

COMMENT ON TABLE kb_object_links IS
    '知识与本体对象互引（relation: knowledge_mentions/'
    'knowledge_supports_object/knowledge_defines_rule）';

-- 验证：SELECT count(*) FROM ontology_types;  -- 期望 >= 22（种子幂等）
