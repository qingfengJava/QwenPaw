-- [变更说明] 账号体系 M2：qwenpaw_users + user_identity_bindings 落 PG + agent_runs 用户筛选索引
-- [变更时间] 2026-09-16
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/feature/agent_run_logs_20260908/test.sql] 是
-- [同步至 db/feature/agent_run_logs_20260908/prod.sql] 是
--
-- 背景：账号存储原为 users.json 文件（M1），项目已全面 PG 化后升级为
-- PG 权威存储（接口不变，无 PG 部署继续走文件路径）。启动时对文件
-- 存量账号做一次幂等导入。
-- alembic twin: 0032_user_accounts_pg

-- 账号主表（username 不可变身份锚点：会话/记忆/运行日志按此归属）
CREATE TABLE IF NOT EXISTS qwenpaw_users (
    tenant_id     VARCHAR(64)  NOT NULL DEFAULT 'default',
    username      VARCHAR(64)  NOT NULL,
    password_hash TEXT         NOT NULL,
    password_salt VARCHAR(64)  NOT NULL DEFAULT '',
    password_algo VARCHAR(16)  NOT NULL DEFAULT 'argon2',
    role          VARCHAR(16)  NOT NULL DEFAULT 'employee',
    display_name  VARCHAR(128) NOT NULL DEFAULT '',
    avatar        VARCHAR(512) NOT NULL DEFAULT '',
    disabled      BOOLEAN      NOT NULL DEFAULT FALSE,
    org_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_qwenpaw_users PRIMARY KEY (tenant_id, username)
);

COMMENT ON TABLE qwenpaw_users IS
'账号主表（M2 权威存储；users.json 保留为无 PG 部署回退）';
COMMENT ON COLUMN qwenpaw_users.username IS
'用户名（不可变身份锚点：会话/记忆/运行日志按此归属）';
COMMENT ON COLUMN qwenpaw_users.password_algo IS
'密码散列算法: argon2, sha256（legacy，登录时透明升级）';
COMMENT ON COLUMN qwenpaw_users.role IS '角色: admin, employee';
COMMENT ON COLUMN qwenpaw_users.org_id IS
'归属组织（租户预留；部门成员关系在 department_members）';

-- 渠道外部身份 → 账号绑定（wechat:openid 等映射到注册用户名）
CREATE TABLE IF NOT EXISTS user_identity_bindings (
    tenant_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    channel          VARCHAR(32)  NOT NULL,
    external_user_id VARCHAR(128) NOT NULL,
    username         VARCHAR(64)  NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_identity_bindings
        PRIMARY KEY (tenant_id, channel, external_user_id)
);

COMMENT ON TABLE user_identity_bindings IS
'渠道外部身份 → 账号绑定（wechat:openid 等映射到注册用户名）';
COMMENT ON COLUMN user_identity_bindings.external_user_id IS
'渠道侧用户标识（openid/userid 等，渠道内唯一）';

-- 运行日志按发起用户筛选/权限过滤的高频路径（employee 仅看自己）
CREATE INDEX IF NOT EXISTS ix_agent_runs_user
ON agent_runs (tenant_id, agent_id, user_id, started_at)
WHERE user_id IS NOT NULL;
