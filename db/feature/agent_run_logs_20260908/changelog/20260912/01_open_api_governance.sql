-- [变更说明] open API 横切治理：新增 open_api_idempotency（幂等回放缓存）+ open_api_audit（调用审计流水）
-- [变更时间] 2026-09-12
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [说明]     /api/open 平面横切协议落地（P4 收尾批次）：
--            ① Idempotency-Key 幂等回放——同 key+幂等键+同请求指纹直接回放缓存响应
--               （TTL 24h 懒过期），同 key 不同指纹 409 冲突；
--            ② 审计流水——全部 /api/open 调用（含 4xx/5xx）落 open_api_audit，
--               管理端可查询（key/expert 过滤）；
--            ③ per-key 限流为进程内存滑动窗口（默认 30 req/min，环境变量可配），
--               限流态不落库。alembic 等价路径：0026。

-- ① 幂等回放缓存表（key 维度隔离；响应 JSONB 整体缓存）
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

-- ② 调用审计流水表（全部 /api/open 请求，含鉴权后的 4xx/5xx）
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
