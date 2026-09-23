-- ============================================================
-- 变更说明: 新增 media_files 表 —— console 聊天上传附件的 PG 持久化
--           （上传双写：本地 media/ 工作副本 + 本表数据库副本；
--            回显端点 GET /api/console/media/{stored_name}
--            优先读本表、回退本地文件）
--           修复链：AI 找不到图片（错误 file:///D:/ 路径）、
--           刷新后图片不回显、图片本体入库三项需求的数据基座
-- 变更时间: 2026-08-16
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0005_media_files（Revises 0004_table_timestamps）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. 媒体文件表（console 上传附件的数据库副本）
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_files (
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
    stored_name VARCHAR(255) NOT NULL,
    file_name   TEXT NOT NULL,
    media_type  TEXT NOT NULL DEFAULT 'application/octet-stream',
    size        BIGINT NOT NULL DEFAULT 0,
    data        BYTEA NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT pk_media_files PRIMARY KEY (tenant_id, stored_name)
);

COMMENT ON TABLE media_files IS 'console 聊天上传媒体文件表（POST /api/console/upload 双写入库，回显端点优先读取）';
COMMENT ON COLUMN media_files.tenant_id IS '租户标识（多租户预留，单租户部署恒为 default）';
COMMENT ON COLUMN media_files.stored_name IS '存储名（{32位hex}_{原始安全文件名}，与 tenant_id 组成联合主键，同时是本地 media/ 目录下的文件名）';
COMMENT ON COLUMN media_files.file_name IS '原始文件名（展示用，已做安全清洗）';
COMMENT ON COLUMN media_files.media_type IS 'MIME 类型: image/png、application/pdf 等（缺省 application/octet-stream）';
COMMENT ON COLUMN media_files.size IS '文件字节数';
COMMENT ON COLUMN media_files.data IS '文件内容二进制（BYTEA）';
COMMENT ON COLUMN media_files.created_at IS '创建时间（DB 自动维护，UTC）';
COMMENT ON COLUMN media_files.updated_at IS '更新时间（DB 自动维护，UTC）';

-- ------------------------------------------------------------
-- 2. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0005_media_files';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0005_media_files');
    END IF;
END $$;

COMMIT;
