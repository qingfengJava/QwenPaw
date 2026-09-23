-- ============================================================
-- 变更说明: 新增 xian_shares 表 —— XianWork 分享链接登记表
--           （能力 URL 模型：token 即凭据，POST /api/xian/shares
--            铸造、同会话重复分享幂等复用同一 token；公开端点
--            GET /api/xian/shares/view/{token} 凭 token 免登录读取
--            会话元信息 + 完整对话 + 会话登记文件，文件下载走
--            /view/{token}/files/{stored_name} 公开代理并做归属校验；
--            创建/撤销仍要求登录且校验会话归属，公开前缀已在
--            app/auth.py::_PUBLIC_PREFIXES 登记）
--           场景：一个对话里产出多份文档，用一条链接在浏览器
--            打开只读分享页浏览/下载，优于逐个导出文件
-- 变更时间: 2026-08-17
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0008_xian_shares（Revises 0007_media_registry）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 分享链接登记表（一个会话一条有效分享，token 内容寻址不可猜）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS xian_shares (
    tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
    token      VARCHAR(64) NOT NULL,
    chat_id    VARCHAR(128) NOT NULL,
    owner_id   VARCHAR(128) NOT NULL,
    revoked    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_xian_shares PRIMARY KEY (tenant_id, token)
);

COMMENT ON TABLE xian_shares IS 'XianWork 分享链接登记表（能力 URL：token 即凭据；同会话重复分享幂等复用，撤销置 revoked=true）';
COMMENT ON COLUMN xian_shares.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN xian_shares.token IS '分享令牌（secrets.token_urlsafe(18)，不可猜测；与 tenant_id 组成联合主键，公开视图端点唯一入参）';
COMMENT ON COLUMN xian_shares.chat_id IS '被分享会话 ID（chats.id；会话删除后分享视图自然 404）';
COMMENT ON COLUMN xian_shares.owner_id IS '铸造分享的账号（xian 面 username，RLS owner_isolation 隔离键）';
COMMENT ON COLUMN xian_shares.revoked IS '是否已撤销（true 后公开端点一律 404；当前版本无撤销 UI，删除会话即等效失效）';
COMMENT ON COLUMN xian_shares.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN xian_shares.updated_at IS '更新时间（DB 自动维护，UTC）';

CREATE UNIQUE INDEX IF NOT EXISTS ux_xian_shares_chat
    ON xian_shares (tenant_id, chat_id)
    WHERE revoked = false;

CREATE INDEX IF NOT EXISTS ix_xian_shares_owner
    ON xian_shares (tenant_id, owner_id);

-- ------------------------------------------------------------
-- 2. Owner 隔离 RLS（PERMISSIVE 灰度策略；无 DROP 语句的幂等形态，
--    与 xian_workspaces 同款）
-- ------------------------------------------------------------

ALTER TABLE xian_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE xian_shares FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'xian_shares' AND policyname = 'owner_isolation'
    ) THEN
        EXECUTE format(
            'CREATE POLICY owner_isolation ON %I AS PERMISSIVE FOR ALL USING (%s) WITH CHECK (%s)',
            'xian_shares',
            'current_setting(''app.current_owner'', true) IS NULL ' ||
            'OR current_setting(''app.current_owner'', true) = '''' ' ||
            'OR owner_id IS NULL ' ||
            'OR owner_id = current_setting(''app.current_owner'', true)',
            'current_setting(''app.current_owner'', true) IS NULL ' ||
            'OR current_setting(''app.current_owner'', true) = '''' ' ||
            'OR owner_id IS NULL ' ||
            'OR owner_id = current_setting(''app.current_owner'', true)'
        );
    END IF;
END $$;

-- ------------------------------------------------------------
-- 3. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0008_xian_shares';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0008_xian_shares');
    END IF;
END $$;

COMMIT;
