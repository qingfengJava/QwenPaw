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
