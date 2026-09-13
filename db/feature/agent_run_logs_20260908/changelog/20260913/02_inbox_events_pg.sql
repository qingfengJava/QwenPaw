-- [变更说明] 收件箱事件 PG 权威平面 + 可移植应用密钥：新增 inbox_events / app_portable_keys 两表
--            （inbox_events：通知事件此前仅存于 WORKING_DIR inbox_events.json 单文件，换设备/重装即全丢；
--             dual/pg 后端下 PG 为唯一权威，json 文件仅作首次启用一次性 backfill 种子后清空）
--            （app_portable_keys：provider api_key 的 ENC1: 可移植密文密钥材料，
--             解决本机 keychain master key 跨设备不可解密导致的多设备配置恢复缺口）
-- [变更时间] 2026-09-13
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
-- [等价 alembic] 0028_inbox_events_pg

CREATE TABLE IF NOT EXISTS inbox_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    event_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(64) NOT NULL DEFAULT 'default',
    source_type VARCHAR(32) NOT NULL DEFAULT '',
    source_id VARCHAR(128) NOT NULL DEFAULT '',
    event_type VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT '',
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inbox_events_event UNIQUE (tenant_id, event_id)
);

CREATE INDEX IF NOT EXISTS ix_inbox_events_agent
    ON inbox_events (tenant_id, agent_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_inbox_events_source
    ON inbox_events (tenant_id, source_type);

COMMENT ON TABLE inbox_events IS
    '收件箱通知事件权威表（inbox_events.json 单文件平面的 PG 权威化，append-only 事件流；json 后端零动作、dual/pg 权威，文件仅一次性 backfill 种子）';
COMMENT ON COLUMN inbox_events.tenant_id IS
    '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN inbox_events.event_id IS
    '事件 ID（UUID，原 json 平面的 id 字段，租户内唯一）';
COMMENT ON COLUMN inbox_events.agent_id IS
    '数字员工 ID（default 表示全局事件）';
COMMENT ON COLUMN inbox_events.source_type IS
    '事件来源类型（cron/mailbox/skill 等，控制台过滤维度）';
COMMENT ON COLUMN inbox_events.source_id IS
    '来源实体 ID（如任务 ID、邮件 ID，可为空串）';
COMMENT ON COLUMN inbox_events.event_type IS
    '事件业务类型（created/failed/run_finished 等）';
COMMENT ON COLUMN inbox_events.status IS
    '事件状态（payload 演进的可查询投影，控制台筛选用）';
COMMENT ON COLUMN inbox_events.severity IS
    '严重级别: info-信息, warning-警告, error-错误';
COMMENT ON COLUMN inbox_events.title IS
    '事件标题（控制台列表展示）';
COMMENT ON COLUMN inbox_events.body IS
    '事件正文（控制台详情展示）';
COMMENT ON COLUMN inbox_events.payload IS
    '事件扩展载荷 JSONB（run_id/acl_sender_address 等结构化上下文）';
COMMENT ON COLUMN inbox_events.is_read IS
    '是否已读（布尔投影，未读计数与全部已读操作的目标列）';
COMMENT ON COLUMN inbox_events.created_at IS
    '事件时间（Unix 浮点秒，与原 json 平面字段语义一致）';
COMMENT ON COLUMN inbox_events.updated_at IS
    '入库/更新时间（已读标记等操作时刷新）';

CREATE TABLE IF NOT EXISTS app_portable_keys (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    key_name VARCHAR(64) NOT NULL,
    key_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_app_portable_keys UNIQUE (tenant_id, key_name)
);

COMMENT ON TABLE app_portable_keys IS
    '可移植应用级加密密钥表（跨设备可解密密文的密钥材料，安全边界等价于 PG 自身访问控制；与 OS keychain 绑定的本机 master key 互补）';
COMMENT ON COLUMN app_portable_keys.tenant_id IS
    '租户 ID（多租户预留，现阶段固定 default）';
COMMENT ON COLUMN app_portable_keys.key_name IS
    '密钥用途名（provider_api_key 为厂商 api_key 可移植加密密钥）';
COMMENT ON COLUMN app_portable_keys.key_value IS
    '密钥材料本体（Fernet key 的 base64 编码；泄露面=PG 访问权）';
COMMENT ON COLUMN app_portable_keys.created_at IS
    '创建时间（首次使用时生成）';
COMMENT ON COLUMN app_portable_keys.updated_at IS
    '更新时间（预留轮换场景）';
