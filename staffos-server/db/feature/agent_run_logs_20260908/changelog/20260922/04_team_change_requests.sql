-- [变更说明] P5 AI 修改安全闭环：新增 team_change_requests 持久化提案表
-- [变更时间] 2026-09-22
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是

-- AI 对话修改团队配置时，模型只能提出候选变更请求，不能直接写草稿。
-- 用户在聊天界面确认后才由 HTTP 确认端点执行 CAS 写操作。
-- 本表持久化变更请求的生命周期：pending → applying → applied/rejected/expired/conflict/failed。

CREATE TABLE IF NOT EXISTS team_change_requests (
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
    request_id      VARCHAR(64)  NOT NULL,
    team_id         VARCHAR(64)  NOT NULL,
    operator_id     VARCHAR(128) NOT NULL,
    session_id      VARCHAR(128) NOT NULL DEFAULT '',
    kind            VARCHAR(32)  NOT NULL DEFAULT 'save_draft',
    base_revision   INTEGER      NOT NULL DEFAULT 0,
    base_published_version INTEGER NOT NULL DEFAULT 0,
    candidate_hash  VARCHAR(64)  NOT NULL DEFAULT '',
    candidate_payload JSONB      NOT NULL DEFAULT '{}'::jsonb,
    validation_result JSONB      NOT NULL DEFAULT '{}'::jsonb,
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    error_message   TEXT         NOT NULL DEFAULT '',
    expires_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (now() + interval '30 minutes'),
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    applied_at      TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_team_change_requests PRIMARY KEY (tenant_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_team_change_requests_team
    ON team_change_requests (tenant_id, team_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_team_change_requests_status
    ON team_change_requests (tenant_id, status)
    WHERE status IN ('pending', 'applying');

COMMENT ON TABLE team_change_requests IS 'AI 修改团队配置的持久化提案（用户确认后执行）';
COMMENT ON COLUMN team_change_requests.tenant_id IS '租户标识';
COMMENT ON COLUMN team_change_requests.request_id IS '提案唯一 ID（UUID）';
COMMENT ON COLUMN team_change_requests.team_id IS '目标团队 ID';
COMMENT ON COLUMN team_change_requests.operator_id IS '发起操作的用户名（认证上下文）';
COMMENT ON COLUMN team_change_requests.session_id IS '来源会话 ID（AI 对话 session）';
COMMENT ON COLUMN team_change_requests.kind IS '提案类型：save_draft / publish';
COMMENT ON COLUMN team_change_requests.base_revision IS '创建时的草稿修订号（CAS 基准）';
COMMENT ON COLUMN team_change_requests.base_published_version IS '创建时的已发布版本号';
COMMENT ON COLUMN team_change_requests.candidate_hash IS '候选内容 SHA-256 摘要（防篡改比对）';
COMMENT ON COLUMN team_change_requests.candidate_payload IS '候选变更内容（JSON 结构化补丁）';
COMMENT ON COLUMN team_change_requests.validation_result IS '校验结果（issues 列表 + 差异卡）';
COMMENT ON COLUMN team_change_requests.status IS '状态：pending/applying/applied/rejected/expired/conflict/failed';
COMMENT ON COLUMN team_change_requests.error_message IS '失败/冲突时的错误信息';
COMMENT ON COLUMN team_change_requests.expires_at IS '候选过期时间（默认 30 分钟）';
COMMENT ON COLUMN team_change_requests.created_at IS '创建时间';
COMMENT ON COLUMN team_change_requests.updated_at IS '状态更新时间';
COMMENT ON COLUMN team_change_requests.applied_at IS '实际执行时间';
